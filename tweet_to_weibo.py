#!/usr/bin/env python3

# 这个脚本用于从X（Twitter）抓取指定公众艺人的推文，
# 使用AI工具翻译成简体中文，然后发布到该艺人的微博账号上。

import os
import json
import time
import logging
import requests
import configparser
import argparse
import random
import subprocess
import platform
from datetime import datetime, timedelta
import tweepy
import openai
from weibo import Client as WeiboClient
from urllib.parse import urlparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import html
import re
from http.client import IncompleteRead
import traceback

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tweet_to_weibo.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Tweet2Weibo")

# 解析命令行参数
parser = argparse.ArgumentParser(description='从X抓取推文，翻译后发布到微博')
parser.add_argument('--test', action='store_true', help='测试模式，不实际发布到微博')
parser.add_argument('--force', action='store_true', help='强制检查新推文，忽略缓存')
parser.add_argument('--artist', type=str, help='要抓取的X用户名，覆盖配置文件中的设置')
parser.add_argument('--count', type=int, default=5, help='要抓取的最大推文数量')
parser.add_argument('--once', action='store_true', help='仅运行一次，不循环检查')
parser.add_argument('--windows-path', type=str, help='Windows系统保存路径，用于保存推文原文')
args = parser.parse_args()

# 读取配置文件
config = configparser.ConfigParser()
config_file = 'config.ini'

if not os.path.exists(config_file):
    logger.error(f"配置文件 {config_file} 不存在，请基于 config.example.ini 创建")
    exit(1)

config.read(config_file)

# 从配置文件中读取API密钥和设置
X_API_KEY = config['API_KEYS']['X_API_KEY']
X_API_SECRET = config['API_KEYS']['X_API_SECRET']
X_ACCESS_TOKEN = config['API_KEYS']['X_ACCESS_TOKEN']
X_ACCESS_TOKEN_SECRET = config['API_KEYS']['X_ACCESS_TOKEN_SECRET']
X_BEARER_TOKEN = config['API_KEYS'].get('X_BEARER_TOKEN', '')  # 兼容旧配置文件

# 处理 Bearer Token 中的转义字符
if X_BEARER_TOKEN:
    X_BEARER_TOKEN = X_BEARER_TOKEN.replace('%%', '%')

OPENAI_API_KEY = config['OPENAI']['OPENAI_API_KEY']

WEIBO_APP_KEY = config['WEIBO']['WEIBO_APP_KEY']
WEIBO_APP_SECRET = config['WEIBO']['WEIBO_APP_SECRET']
WEIBO_ACCESS_TOKEN = config['WEIBO']['WEIBO_ACCESS_TOKEN']

# 读取设置，命令行参数优先
X_USERNAME = args.artist or config['SETTINGS']['X_USERNAME']
TEST_MODE = args.test or config['SETTINGS'].getboolean('TEST_MODE', fallback=True)
CACHE_EXPIRY = int(config['SETTINGS'].getboolean('CACHE_EXPIRY_MINUTES', fallback=15))
MAX_TWEETS = args.count

# 添加备用翻译设置
USE_BACKUP_TRANSLATOR = config['SETTINGS'].getboolean('USE_BACKUP_TRANSLATOR', fallback=True)
BACKUP_TRANSLATOR = config['SETTINGS'].get('BACKUP_TRANSLATOR', 'google')  # 支持 google, baidu, free

# 文件路径
PROCESSED_TWEETS_FILE = "processed_tweets.json"
CACHE_FILE = f"cache_{X_USERNAME}_tweets.json"

def load_processed_tweets():
    """加载已处理过的推文ID列表"""
    if os.path.exists(PROCESSED_TWEETS_FILE):
        try:
            with open(PROCESSED_TWEETS_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"无法解析 {PROCESSED_TWEETS_FILE} 文件")
            return []
    return []

def save_processed_tweet(tweet_id):
    """保存已处理的推文ID"""
    processed_tweets = load_processed_tweets()
    if tweet_id not in processed_tweets:
        processed_tweets.append(tweet_id)
        with open(PROCESSED_TWEETS_FILE, 'w') as f:
            json.dump(processed_tweets, f)
            
def is_valid_cache():
    """检查缓存是否有效"""
    if args.force:
        return False
        
    if not os.path.exists(CACHE_FILE):
        return False
        
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            
        cache_time = datetime.fromisoformat(cache_data['timestamp'])
        current_time = datetime.now()
        # 检查是否在缓存过期时间内
        if (current_time - cache_time).total_seconds() < CACHE_EXPIRY * 60:
            return True
    except Exception as e:
        logger.error(f"检查缓存时出错: {e}")
        
    return False

def load_tweets_from_cache():
    """从缓存加载推文"""
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            
        # 从缓存创建推文对象
        tweets = []
        for tweet_data in cache_data['tweets']:
            tweet = type('Tweet', (), {})()
            tweet.id = tweet_data['id']
            tweet.full_text = tweet_data['text']
            tweet.created_at = datetime.fromisoformat(tweet_data['created_at'])
            
            # 添加媒体信息
            tweet.extended_entities = {}
            if 'media' in tweet_data:
                tweet.extended_entities['media'] = tweet_data['media']
                
            tweets.append(tweet)
            
        logger.info(f"从缓存加载了 {len(tweets)} 条推文")
        return tweets
    except Exception as e:
        logger.error(f"从缓存加载推文时出错: {e}")
        return []

def save_tweets_to_cache(tweets_data):
    """保存推文到缓存"""
    try:
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'tweets': tweets_data
        }
        
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"已将 {len(tweets_data)} 条推文保存到缓存")
    except Exception as e:
        logger.error(f"保存推文到缓存时出错: {e}")

@retry(
    stop=stop_after_attempt(3), 
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((tweepy.TweepyException, requests.exceptions.RequestException))
)
def get_tweets_from_x():
    """从X获取指定用户的最新推文 (使用 X API v2 和 Bearer Token)，包含速率限制处理"""
    # 如果缓存有效，直接从缓存加载
    if is_valid_cache():
        return load_tweets_from_cache()
    
    # 尝试使用X API
    try:
        # 测试模式下，尝试调用真实的 X API v2，如果失败则使用模拟数据
        if TEST_MODE:
            logger.info(f"测试模式：尝试从 X 获取 @{X_USERNAME} 的真实推文 (使用 Bearer Token)")
        else:
            logger.info(f"尝试使用X API获取 @{X_USERNAME} 的推文")
        
        # 创建 v2 API 客户端，使用 Bearer Token
        client = tweepy.Client(bearer_token=X_BEARER_TOKEN)
        
        # 首先获取用户 ID
        user = client.get_user(username=X_USERNAME)
        
        if not user.data:
            logger.warning(f"未找到用户 @{X_USERNAME}")
            if TEST_MODE:
                return get_mock_tweets()
            else:
                # 切换到无API抓取方式
                return get_tweets_without_api()
                
        user_id = user.data.id
        logger.info(f"找到用户 ID: {user_id}")
        
        # 获取用户推文
        tweets_response = client.get_users_tweets(
            id=user_id,
            max_results=MAX_TWEETS,
            tweet_fields=['created_at', 'text'],
            expansions=['attachments.media_keys'],
            media_fields=['type', 'url', 'preview_image_url', 'media_key']
        )
        
        if not tweets_response.data:
            logger.warning(f"未找到用户推文")
            if TEST_MODE:
                return get_mock_tweets()
            else:
                # 切换到无API抓取方式
                return get_tweets_without_api()
        
        # 转换为自定义的推文对象，与原有流程兼容
        tweets = []
        
        # 准备缓存数据
        cache_data = []
        
        # 创建媒体查找字典
        media_lookup = {}
        if tweets_response.includes and 'media' in tweets_response.includes:
            for media in tweets_response.includes['media']:
                media_lookup[media.media_key] = {
                    'type': media.type,
                    'url': getattr(media, 'url', None) or getattr(media, 'preview_image_url', None)
                }
        
        for tweet_data in tweets_response.data:
            # 创建推文对象
            tweet = type('Tweet', (), {})()
            tweet.id = tweet_data.id
            tweet.full_text = tweet_data.text
            tweet.created_at = tweet_data.created_at
            
            # 处理媒体附件
            tweet.extended_entities = {'media': []}
            
            if hasattr(tweet_data, 'attachments') and hasattr(tweet_data.attachments, 'media_keys'):
                for media_key in tweet_data.attachments.media_keys:
                    if media_key in media_lookup:
                        media_info = media_lookup[media_key]
                        tweet.extended_entities['media'].append({
                            'type': media_info['type'],
                            'media_url': media_info['url']
                        })
            
            tweets.append(tweet)
            
            # 添加到缓存数据
            tweet_cache = {
                'id': tweet_data.id,
                'text': tweet_data.text,
                'created_at': tweet_data.created_at.isoformat()
            }
            
            # 添加媒体信息到缓存
            if tweet.extended_entities['media']:
                tweet_cache['media'] = tweet.extended_entities['media']
            
            cache_data.append(tweet_cache)
        
        # 保存到缓存
        save_tweets_to_cache(cache_data)
        
        logger.info(f"成功从X API获取了 {len(tweets)} 条推文")
        return tweets
        
    except tweepy.TooManyRequests as e:
        logger.warning(f"X API请求次数超过限制，切换到无API抓取方式: {e}")
        return get_tweets_without_api()
    except tweepy.TweepyException as e:
        if "429" in str(e):
            logger.warning(f"X API请求次数超过限制，切换到无API抓取方式: {e}")
            return get_tweets_without_api()
        logger.error(f"X API请求失败: {e}")
        if TEST_MODE:
            return get_mock_tweets()
        else:
            return get_tweets_without_api()
    except Exception as e:
        logger.error(f"获取推文时出错: {e}")
        logger.debug(traceback.format_exc())
        if TEST_MODE:
            return get_mock_tweets()
        else:
            # 切换到无API抓取方式
            return get_tweets_without_api()

def get_tweets_without_api():
    """使用x_scraper.py无API方式获取推文"""
    logger.info(f"使用无API方式获取 @{X_USERNAME} 的推文")
    
    try:
        # 确保x_scraper.py存在
        if not os.path.exists('x_scraper.py'):
            logger.error("找不到x_scraper.py文件，无法使用无API方式")
            return []
        
        # 构建命令参数
        cmd = [
            'python', 
            'x_scraper.py', 
            '--username', X_USERNAME,
            '--count', str(MAX_TWEETS),
            '--once',
            '--force'  # 强制抓取，不使用缓存
        ]
        
        # 执行命令
        logger.info(f"执行命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"无API抓取失败: {result.stderr}")
            return []
        
        # 检查是否生成了缓存文件
        cache_file = f"cache_{X_USERNAME}_tweets.json"
        if not os.path.exists(cache_file):
            logger.error(f"未找到缓存文件 {cache_file}")
            return []
        
        # 加载缓存文件
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        
        if 'tweets' not in cache_data or not cache_data['tweets']:
            logger.warning("缓存文件中没有推文数据")
            return []
        
        # 转换为主程序使用的格式
        tweets = []
        for tweet_data in cache_data['tweets']:
            # 创建推文对象
            tweet = type('Tweet', (), {})()
            tweet.id = tweet_data['id']
            tweet.full_text = tweet_data['content']
            
            # 处理日期
            try:
                if 'created_at' in tweet_data and tweet_data['created_at']:
                    # 尝试解析ISO格式
                    if 'T' in tweet_data['created_at']:
                        tweet.created_at = datetime.fromisoformat(tweet_data['created_at'].replace('Z', '+00:00'))
                    # 尝试解析Nitter格式（例如："Apr 26, 2025, 15:30:45"）
                    else:
                        try:
                            tweet.created_at = datetime.strptime(tweet_data['created_at'], "%b %d, %Y, %H:%M:%S")
                        except ValueError:
                            tweet.created_at = datetime.now()
                else:
                    tweet.created_at = datetime.now()
            except Exception as e:
                logger.warning(f"解析日期失败: {e}，使用当前时间")
                tweet.created_at = datetime.now()
            
            # 处理媒体
            tweet.extended_entities = {'media': []}
            if 'media' in tweet_data:
                for media in tweet_data['media']:
                    if 'type' in media and media['type'] == 'photo' and 'url' in media:
                        tweet.extended_entities['media'].append({
                            'type': 'photo',
                            'media_url': media['url']
                        })
            
            tweets.append(tweet)
        
        logger.info(f"成功从无API方式获取了 {len(tweets)} 条推文")
        return tweets
        
    except Exception as e:
        logger.error(f"无API获取推文失败: {e}")
        logger.debug(traceback.format_exc())
        return []

def get_mock_tweets():
    """生成模拟的推文数据"""
    logger.info("生成模拟推文数据")
    # 创建模拟的推文对象
    class MockTweet:
        def __init__(self, id, text, has_media=False):
            self.id = id
            self.full_text = text
            self.created_at = datetime.now() - timedelta(hours=random.randint(1, 24))
            # 模拟媒体附件
            self.extended_entities = {'media': []}
            if has_media:
                self.extended_entities['media'].append({
                    'type': 'photo',
                    'media_url': 'https://dummyimage.com/600x400/000/fff&text=Mock+Image'
                })
    
    # 返回一些模拟的推文
    return [
        MockTweet("1", "This is a test tweet from our mock data. #testing", True),
        MockTweet("2", "Another mock tweet to demonstrate the translation functionality."),
        MockTweet("3", "今日も撮影楽しかったですー！みんなありがとう〜 #日本語ツイート", True)
    ]

def translate_with_free_api(text, source_lang='auto', target_lang='zh-CN'):
    """使用免费API进行翻译，不需要API密钥"""
    logger.info(f"使用备用翻译服务 (Free API)")
    try:
        # 判断是主要为日语还是英语
        def is_mainly_japanese(text):
            jp_chars = len([c for c in text if ord(c) > 0x3000])
            return jp_chars > len(text) * 0.1
            
        is_jp = is_mainly_japanese(text)
        source_lang = 'ja' if is_jp else 'en'
        
        # 使用免费翻译服务
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q={html.escape(text)}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            # 解析JSON响应
            result = response.json()
            translated_text = ''.join([item[0] for item in result[0] if item[0]])
            return translated_text
        else:
            logger.error(f"备用翻译服务请求失败，状态码: {response.status_code}")
            return f"[翻译失败] {text[:50]}..."
    except Exception as e:
        logger.error(f"备用翻译服务出错: {e}")
        return f"[翻译失败] {text[:50]}..."

@retry(
    stop=stop_after_attempt(3), 
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError))
)
def translate_text_with_openai(text):
    """使用OpenAI API翻译文本，如果配额不足则使用备用翻译服务"""
    
    # 判断文本是否主要为日语
    def is_mainly_japanese(text):
        # 简单检测文本是否包含日语字符
        jp_chars = len([c for c in text if ord(c) > 0x3000])
        return jp_chars > len(text) * 0.1  # 如果超过10%的字符是日语，认为是日语文本
    
    is_jp = is_mainly_japanese(text)
    
    # 测试模式下，尝试调用真实的 OpenAI API
    if TEST_MODE:
        try:
            logger.info(f"测试模式：尝试使用 OpenAI API 翻译文本")
            # 设置OpenAI API密钥
            openai.api_key = OPENAI_API_KEY
            
            # 为测试模式提供更简单的提示，减少API消耗
            if random.random() < 0.5:  # 50%的概率调用真实API
                # 调用API进行翻译
                response = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "请将输入文本准确翻译成简体中文。"},
                        {"role": "user", "content": text}
                    ],
                    max_tokens=150
                )
                
                # 提取翻译结果
                translated_text = response.choices[0].message.content.strip()
                logger.info(f"测试模式：翻译完成")
                return translated_text
            else:
                logger.info(f"测试模式：跳过API调用，返回模拟翻译")
                if is_jp:
                    return f"[测试翻译-日语] {text[:30]}..."
                else:
                    return f"[测试翻译-英语] {text[:30]}..."
        
        except openai.RateLimitError as e:
            logger.error(f"测试模式：OpenAI API速率限制错误: {e}")
            if USE_BACKUP_TRANSLATOR:
                logger.info("切换到备用翻译服务")
                return translate_with_free_api(text)
            return f"[测试翻译失败] {text[:30]}..."
        except openai.InsufficientQuotaError as e:
            logger.error(f"测试模式：OpenAI API配额不足: {e}")
            if USE_BACKUP_TRANSLATOR:
                logger.info("切换到备用翻译服务")
                return translate_with_free_api(text)
            return f"[测试翻译失败] {text[:30]}..."
        except Exception as e:
            logger.error(f"测试模式：翻译失败，错误: {e}，返回模拟翻译")
            if is_jp:
                return f"[测试翻译-日语] {text[:30]}..."
            else:
                return f"[测试翻译-英语] {text[:30]}..."
    
    try:
        # 设置OpenAI API密钥
        openai.api_key = OPENAI_API_KEY
        
        # 针对日语和英语使用不同的提示
        if is_jp:
            system_prompt = "你是专业的日语翻译专家，精通日本文化、网络用语、表情符号和日本艺人常用词汇。请将以下日语内容准确翻译成自然流畅的简体中文，保留原文的风格、情感和文化内涵。保留原文中的表情符号、标签和@提及。"
        else:
            system_prompt = "你是专业的英语翻译专家，精通英语文化、网络用语、表情符号和国际交流。请将以下英语内容准确翻译成自然流畅的简体中文，保留原文的风格、情感和文化内涵。保留原文中的表情符号、标签和@提及。"
        
        # 调用API进行翻译
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请翻译以下文本：\n\n{text}"}
            ]
        )
        
        # 提取翻译结果
        translated_text = response.choices[0].message.content.strip()
        logger.info(f"翻译完成")
        return translated_text
    
    except openai.RateLimitError as e:
        logger.error(f"OpenAI API速率限制错误: {e}")
        if USE_BACKUP_TRANSLATOR:
            logger.info("切换到备用翻译服务")
            return translate_with_free_api(text)
        return ""
    except openai.InsufficientQuotaError as e:
        logger.error(f"OpenAI API配额不足: {e}")
        if USE_BACKUP_TRANSLATOR:
            logger.info("切换到备用翻译服务")
            return translate_with_free_api(text)
        return ""
    except Exception as e:
        logger.error(f"翻译时出错: {e}")
        logger.error(traceback.format_exc())
        if USE_BACKUP_TRANSLATOR:
            logger.info("尝试使用备用翻译服务")
            return translate_with_free_api(text)
        return ""

@retry(
    stop=stop_after_attempt(3), 
    wait=wait_exponential(multiplier=1, min=4, max=30)
)
def post_to_weibo(text, media_urls=None):
    """发布内容到微博"""
    # 测试模式下，只打印不实际发布
    if TEST_MODE:
        logger.info(f"测试模式：将发布到微博的内容: {text}")
        if media_urls:
            logger.info(f"测试模式：包含 {len(media_urls)} 张图片")
        return True
    
    try:
        # 创建微博客户端
        client = WeiboClient(
            WEIBO_APP_KEY,
            WEIBO_APP_SECRET,
            WEIBO_ACCESS_TOKEN
        )
        
        # 如果有媒体文件，先下载并上传
        pic_ids = []
        if media_urls and len(media_urls) > 0:
            for i, url in enumerate(media_urls[:9]):  # 微博最多支持9张图片
                try:
                    # 下载图片
                    local_filename = f"temp_image_{i}.jpg"
                    response = requests.get(url, stream=True)
                    if response.status_code == 200:
                        with open(local_filename, 'wb') as f:
                            for chunk in response.iter_content(1024):
                                f.write(chunk)
                        
                        # 上传图片到微博
                        with open(local_filename, 'rb') as f:
                            pic_upload_response = client.upload.pic.upload(pic=f)
                            if 'pic_id' in pic_upload_response:
                                pic_ids.append(pic_upload_response['pic_id'])
                                logger.info(f"图片 {i+1} 上传成功")
                        
                        # 删除临时文件
                        os.remove(local_filename)
                    else:
                        logger.error(f"下载图片失败: {url}")
                except Exception as e:
                    logger.error(f"处理图片时出错: {e}")
        
        # 发布微博
        if pic_ids:
            response = client.statuses.upload.post(status=text, pic_id=",".join(pic_ids))
        else:
            response = client.statuses.update.post(status=text)
        
        if 'id' in response:
            logger.info(f"已发布到微博，微博ID: {response['id']}")
            return True
        else:
            logger.error(f"发布到微博失败，响应: {response}")
            return False
            
    except Exception as e:
        logger.error(f"发布到微博时出错: {e}")
        raise  # 重新抛出异常，触发重试机制

def save_tweets_to_windows(tweets, username):
    """保存推文到Windows系统"""
    if not args.windows_path:
        logger.info("未指定Windows保存路径，跳过保存到Windows系统")
        return False
    
    try:
        # 检查是否在WSL环境中
        is_wsl = "microsoft" in platform.uname().release.lower()
        
        if not is_wsl:
            logger.warning("当前不是WSL环境，无法使用/mnt路径保存到Windows，尝试直接保存")
            windows_path = args.windows_path
        else:
            # 处理Windows路径
            # 如果提供的是Windows格式路径（如C:/Users/...），将其转换为WSL路径格式
            if ':' in args.windows_path:
                # 从Windows路径格式（如C:/Users/username/Documents）转换为WSL格式
                drive_letter = args.windows_path[0].lower()
                path_part = args.windows_path[2:].replace('\\', '/')
                windows_path = f"/mnt/{drive_letter}/{path_part}"
            else:
                # 已经是WSL路径格式
                windows_path = args.windows_path
        
        # 创建目标目录（如果不存在）
        os.makedirs(windows_path, exist_ok=True)
        
        # 生成文件名（使用日期和用户名）
        current_date = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{username}_api_tweets_{current_date}.json"
        full_path = os.path.join(windows_path, filename)
        
        # 转换tweepy对象为可序列化的字典列表
        tweets_json = []
        for tweet in tweets:
            tweet_dict = {
                'id': str(tweet.id),
                'text': tweet.full_text,
                'created_at': tweet.created_at.isoformat(),
                'url': f"https://twitter.com/{username}/status/{tweet.id}"
            }
            
            # 添加媒体信息（如果有）
            if hasattr(tweet, 'extended_entities') and tweet.extended_entities and 'media' in tweet.extended_entities:
                media_list = []
                for media in tweet.extended_entities['media']:
                    media_list.append({
                        'type': media.get('type', 'photo'),
                        'url': media.get('media_url_https', '')
                    })
                tweet_dict['media'] = media_list
            
            tweets_json.append(tweet_dict)
        
        # 保存推文到文件
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(tweets_json, f, ensure_ascii=False, indent=2)
            
        logger.info(f"已将 {len(tweets_json)} 条推文原文保存到Windows系统: {full_path}")
        return True
    except Exception as e:
        logger.error(f"保存推文到Windows系统时出错: {e}")
        logger.debug(traceback.format_exc())
        return False

def process_tweets():
    """处理获取到的推文"""
    processed_tweets = load_processed_tweets()
    
    try:
        # 获取推文
        if TEST_MODE and random.random() < 0.2:  # 20%概率测试无API模式
            logger.info("测试模式: 随机使用模拟数据")
            tweets = get_mock_tweets()
        else:
            try:
                # 首先尝试使用API获取
                tweets = get_tweets_from_x()
            except Exception as e:
                logger.error(f"使用API获取推文失败: {e}")
                # 如果API获取失败，尝试无API方式
                logger.info("尝试使用无API方式获取推文...")
                tweets = get_tweets_without_api()
        
        if not tweets:
            logger.warning("未获取到任何推文")
            return
            
        logger.info(f"获取到 {len(tweets)} 条推文")
        
        # 如果指定了Windows保存路径，保存原始推文到Windows系统
        if args.windows_path:
            save_tweets_to_windows(tweets, X_USERNAME)
        
        # 按照时间升序排序
        try:
            tweets.sort(key=lambda x: x.created_at)
        except Exception as e:
            logger.warning(f"无法按时间排序推文: {e}")
        
        # 只处理未处理过的新推文
        new_tweets = []
        for tweet in tweets:
            if str(tweet.id) not in processed_tweets:
                new_tweets.append(tweet)
                
        if not new_tweets:
            logger.info("没有新的推文需要处理")
            return
            
        logger.info(f"有 {len(new_tweets)} 条新推文需要处理")
        
        for tweet in new_tweets:
            try:
                # 提取推文文本
                tweet_text = tweet.full_text
                
                # 跳过转发的推文
                if tweet_text.startswith('RT @'):
                    logger.info(f"跳过转发推文: {tweet.id}")
                    save_processed_tweet(str(tweet.id))
                    continue
                
                # 提取媒体链接（如果有）
                media_urls = []
                if 'media' in tweet.extended_entities:
                    for media in tweet.extended_entities['media']:
                        if media['type'] == 'photo':
                            media_urls.append(media['media_url'])
                
                # 翻译推文文本
                translated_text = translate_text_with_openai(tweet_text)
                
                if translated_text:
                    # 添加原始链接
                    tweet_url = f"https://twitter.com/{X_USERNAME}/status/{tweet.id}"
                    post_text = f"{translated_text}\n\n原文链接: {tweet_url}"
                    
                    # 发布到微博
                    if post_to_weibo(post_text, media_urls):
                        # 保存已处理的推文ID
                        save_processed_tweet(str(tweet.id))
                        logger.info(f"成功处理推文ID {tweet.id}")
                        
                        # 添加随机延迟，避免频繁发布
                        if not TEST_MODE and not args.once:
                            delay = random.randint(5, 15)
                            logger.info(f"等待 {delay} 秒后继续...")
                            time.sleep(delay)
                    else:
                        logger.error(f"发布到微博失败，推文ID {tweet.id}")
                else:
                    logger.error(f"翻译失败，跳过推文ID {tweet.id}")
                
            except Exception as e:
                logger.error(f"处理推文 {tweet.id} 时出错: {e}")

    except Exception as e:
        logger.error(f"处理推文时出错: {e}")
        logger.debug(traceback.format_exc())

if __name__ == "__main__":
    logger.info(f"开始运行推文抓取和发布服务 {'(测试模式)' if TEST_MODE else ''}")
    logger.info(f"目标用户: @{X_USERNAME}")
    if USE_BACKUP_TRANSLATOR:
        logger.info(f"已启用备用翻译服务: {BACKUP_TRANSLATOR}")
    
    # 测试模式下或单次运行模式
    if TEST_MODE or args.once:
        process_tweets()
        logger.info("处理完成")
    else:
        # 正常模式下定期执行
        try:
            while True:
                process_tweets()
                delay = CACHE_EXPIRY * 60  # 转换为秒
                logger.info(f"休眠 {CACHE_EXPIRY} 分钟后再次检查...")
                time.sleep(delay)
        except KeyboardInterrupt:
            logger.info("服务已手动停止") 