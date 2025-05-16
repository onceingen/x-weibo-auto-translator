#!/usr/bin/env python3

# 这个脚本用于从X（Twitter）抓取指定公众艺人的推文，
# 使用AI工具翻译成简体中文，然后发布到该艺人的微博账号上。

import os
import json
import time
import logging
import requests
import configparser
from datetime import datetime
import tweepy
import openai
from weibo import Client as WeiboClient

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

OPENAI_API_KEY = config['OPENAI']['OPENAI_API_KEY']

WEIBO_APP_KEY = config['WEIBO']['WEIBO_APP_KEY']
WEIBO_APP_SECRET = config['WEIBO']['WEIBO_APP_SECRET']
WEIBO_ACCESS_TOKEN = config['WEIBO']['WEIBO_ACCESS_TOKEN']

# 读取设置
X_USERNAME = config['SETTINGS']['X_USERNAME']
TEST_MODE = config['SETTINGS'].getboolean('TEST_MODE', fallback=True)

# 保存已处理推文ID的文件
PROCESSED_TWEETS_FILE = "processed_tweets.json"

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

def get_tweets_from_x():
    """从X获取指定用户的最新推文"""
    # 测试模式下使用模拟数据
    if TEST_MODE:
        logger.info(f"测试模式：使用模拟推文数据")
        # 创建模拟的推文对象
        class MockTweet:
            def __init__(self, id, text):
                self.id = id
                self.full_text = text
                # 模拟没有媒体附件
                self.extended_entities = {}
        
        # 返回一些模拟的推文
        return [
            MockTweet("1", "This is a test tweet from our mock data. #testing"),
            MockTweet("2", "Another mock tweet to demonstrate the translation functionality.")
        ]
    
    try:
        # 创建X API客户端
        auth = tweepy.OAuth1UserHandler(
            X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
        )
        api = tweepy.API(auth)
        
        # 获取已处理过的推文ID列表
        processed_tweets = load_processed_tweets()
        
        # 获取用户最新推文
        tweets = api.user_timeline(screen_name=X_USERNAME, count=10, tweet_mode="extended")
        
        # 过滤出未处理的推文
        new_tweets = [tweet for tweet in tweets if str(tweet.id) not in processed_tweets]
        
        logger.info(f"找到 {len(new_tweets)} 条未处理的推文")
        return new_tweets
    
    except Exception as e:
        logger.error(f"获取推文时出错: {e}")
        return []

def translate_text_with_openai(text):
    """使用OpenAI API翻译文本"""
    # 测试模式下，直接返回原文文本
    if TEST_MODE:
        logger.info(f"测试模式：跳过翻译，原文文本: {text[:50]}..." if len(text) > 50 else f"测试模式：跳过翻译，原文文本: {text}")
        return f"[测试翻译] {text}"
    
    try:
        # 设置OpenAI API密钥
        openai.api_key = OPENAI_API_KEY
        
        # 调用API进行翻译
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "你是一位优秀的翻译，能够将文本准确地翻译成简体中文，同时保持原文的风格和感情。"},
                {"role": "user", "content": f"请将以下文本翻译成简体中文:\n\n{text}"}
            ]
        )
        
        # 提取翻译结果
        translated_text = response.choices[0].message.content.strip()
        logger.info(f"翻译完成")
        return translated_text
    
    except Exception as e:
        logger.error(f"翻译时出错: {e}")
        return ""

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
        return False

def process_tweets():
    """处理推文的主函数"""
    # 获取推文
    tweets = get_tweets_from_x()
    
    if not tweets:
        logger.info("没有找到新推文")
        return
    
    for tweet in tweets:
        try:
            # 提取推文文本
            tweet_text = tweet.full_text
            
            # 提取媒体链接（如果有）
            media_urls = []
            if hasattr(tweet, 'extended_entities') and 'media' in tweet.extended_entities:
                for media in tweet.extended_entities['media']:
                    if media['type'] == 'photo':
                        media_urls.append(media['media_url'])
            
            # 翻译推文文本
            translated_text = translate_text_with_openai(tweet_text)
            
            if translated_text:
                # 添加原始链接（可选）
                tweet_url = f"https://twitter.com/{X_USERNAME}/status/{tweet.id}"
                post_text = f"{translated_text}\n\n原文链接: {tweet_url}"
                
                # 发布到微博
                if post_to_weibo(post_text, media_urls):
                    # 保存已处理的推文ID
                    save_processed_tweet(str(tweet.id))
                    logger.info(f"成功处理推文ID {tweet.id}")
                else:
                    logger.error(f"发布到微博失败，推文ID {tweet.id}")
            else:
                logger.error(f"翻译失败，跳过推文ID {tweet.id}")
                
        except Exception as e:
            logger.error(f"处理推文 {tweet.id} 时出错: {e}")

if __name__ == "__main__":
    logger.info("开始运行推文抓取和发布服务 (测试模式)" if TEST_MODE else "开始运行推文抓取和发布服务")
    
    # 测试模式下只运行一次
    if TEST_MODE:
        process_tweets()
        logger.info("测试完成")
    else:
        # 正常模式下定期执行
        try:
            while True:
                process_tweets()
                logger.info("休眠15分钟后再次检查...")
                time.sleep(15 * 60)  # 15分钟
        except KeyboardInterrupt:
            logger.info("服务已手动停止") 