#!/usr/bin/env python3

# 使用requests-html抓取X（Twitter）推文
# 不需要API，避开API限制问题

import os
import json
import time
import logging
import argparse
import datetime
import sys
import random
import platform
from pathlib import Path
from datetime import datetime, timedelta
from requests_html import HTMLSession
from urllib.parse import urljoin
import re
import traceback

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("x_scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("XScraper")

# 解析命令行参数
parser = argparse.ArgumentParser(description='使用requests-html抓取X推文，无需API')
parser.add_argument('--username', type=str, default='sasakirico', help='要抓取的X用户名，不包含@符号')
parser.add_argument('--count', type=int, default=10, help='每次抓取的最大推文数量')
parser.add_argument('--interval', type=int, default=10, help='检查间隔（分钟）')
parser.add_argument('--once', action='store_true', help='仅运行一次，不循环检查')
parser.add_argument('--output', type=str, default='scraped_tweets.json', help='输出的JSON文件名')
parser.add_argument('--force', action='store_true', help='强制抓取，忽略缓存')
parser.add_argument('--windows-path', type=str, help='Windows系统保存路径，如C:/Users/username/Documents')
parser.add_argument('--test', action='store_true', help='测试模式，使用模拟数据测试Windows保存功能')
args = parser.parse_args()

# 设置参数
USERNAME = args.username
MAX_TWEETS = args.count
INTERVAL_MINUTES = args.interval
OUTPUT_FILE = args.output
PROCESSED_FILE = "processed_tweet_ids.json"
CACHE_FILE = f"cache_{USERNAME}_tweets.json"
CACHE_EXPIRY = 15  # 缓存过期时间（分钟）
WINDOWS_SAVE_PATH = args.windows_path

# Nitter实例列表（可用的替代访问X的服务）
NITTER_INSTANCES = [
    'https://nitter.net',
    'https://nitter.cz',
    'https://nitter.unixfox.eu',
    'https://nitter.1d4.us',
    'https://nitter.kavin.rocks',
    'https://nitter.lacontrevoie.fr',
    'https://nitter.fdn.fr',
    'https://nitter.poast.org',
    'https://nitter.privacydev.net',
    'https://nitter.projectsegfau.lt',
    'https://nitter.pussthecat.org'
]

def load_processed_tweets():
    """加载已处理过的推文ID列表"""
    if os.path.exists(PROCESSED_FILE):
        try:
            with open(PROCESSED_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载已处理推文记录失败: {e}")
            return []
    return []

def save_processed_tweets(processed_ids):
    """保存已处理的推文ID列表"""
    try:
        with open(PROCESSED_FILE, 'w') as f:
            json.dump(processed_ids, f)
    except Exception as e:
        logger.error(f"保存已处理推文记录失败: {e}")

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
        logger.info(f"从缓存加载了 {len(cache_data['tweets'])} 条推文")
        return cache_data['tweets']
    except Exception as e:
        logger.error(f"从缓存加载推文时出错: {e}")
        return []

def scrape_tweets_from_nitter(username, max_count=10):
    """从Nitter实例抓取用户的推文"""
    tweets = []
    session = HTMLSession()
    
    # 随机打乱Nitter实例顺序，避免对单一实例压力过大
    random.shuffle(NITTER_INSTANCES)
    
    # 尝试不同的Nitter实例，直到成功
    for instance in NITTER_INSTANCES:
        try:
            url = f"{instance}/{username}"
            logger.info(f"尝试从 {url} 抓取推文...")
            
            # 随机化User-Agent，减少被检测的可能性
            headers = {
                'User-Agent': random.choice([
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0'
                ]),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'DNT': '1',
            }
            
            response = session.get(url, headers=headers, timeout=15)
            response.raise_for_status()  # 如果请求失败，引发异常
            
            # 确保页面已经完全加载
            try:
                response.html.render(timeout=30, sleep=2)
            except Exception as e:
                logger.warning(f"JavaScript渲染失败，尝试直接解析HTML: {e}")
            
            # 查找推文容器
            tweet_elements = response.html.find('.timeline-item')
            
            if not tweet_elements:
                logger.warning(f"在 {instance} 上未找到推文元素，尝试另一个实例")
                continue
                
            logger.info(f"在 {instance} 上找到 {len(tweet_elements)} 条推文")
            
            for i, tweet_el in enumerate(tweet_elements):
                if i >= max_count:
                    break
                    
                try:
                    # 提取推文ID
                    permalink = tweet_el.find('.tweet-link', first=True)
                    if not permalink:
                        continue
                        
                    tweet_url = permalink.attrs.get('href', '')
                    tweet_id = tweet_url.split('/')[-1]
                    
                    # 检查是否是转发
                    is_retweet = bool(tweet_el.find('.retweet-header', first=True))
                    if is_retweet:
                        logger.info(f"跳过转发推文 {tweet_id}")
                        continue
                    
                    # 提取推文内容
                    content_el = tweet_el.find('.tweet-content', first=True)
                    content = content_el.text if content_el else ''
                    
                    # 提取时间
                    time_el = tweet_el.find('.tweet-date', first=True)
                    tweet_time = ''
                    if time_el and time_el.find('a', first=True):
                        time_link = time_el.find('a', first=True)
                        if 'title' in time_link.attrs:
                            tweet_time = time_link.attrs['title']
                    
                    # 提取媒体
                    media = []
                    media_els = tweet_el.find('.attachments .attachment')
                    for media_el in media_els:
                        img = media_el.find('img', first=True)
                        if img and 'src' in img.attrs:
                            img_src = img.attrs['src']
                            # 确保是完整的URL
                            if img_src.startswith('/'):
                                img_src = urljoin(instance, img_src)
                            media.append({
                                'type': 'photo',
                                'url': img_src
                            })
                    
                    # 创建推文对象
                    tweet = {
                        'id': tweet_id,
                        'content': content,
                        'created_at': tweet_time,
                        'url': f"https://twitter.com/{username}/status/{tweet_id}",
                        'media': media
                    }
                    
                    tweets.append(tweet)
                    logger.info(f"已抓取推文 {tweet_id}")
                    
                except Exception as e:
                    logger.error(f"解析推文时出错: {e}")
                    logger.debug(traceback.format_exc())
                    continue
            
            # 如果成功获取了推文，跳出循环
            if tweets:
                break
                
        except Exception as e:
            logger.error(f"从 {instance} 抓取失败: {e}")
            logger.debug(traceback.format_exc())
            continue
    
    session.close()
    return tweets

def scrape_tweets_directly(username, max_count=10):
    """直接从X网站抓取推文（备用方法）"""
    tweets = []
    session = HTMLSession()
    
    try:
        url = f"https://twitter.com/{username}"
        logger.info(f"尝试从 {url} 抓取推文...")
        
        # 设置请求头，模拟浏览器
        headers = {
            'User-Agent': random.choice([
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0'
            ]),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'TE': 'Trailers',
        }
        
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # 尝试渲染JavaScript
        try:
            response.html.render(timeout=40, sleep=3, keep_page=True)
        except Exception as e:
            logger.warning(f"JavaScript渲染失败，将尝试直接解析HTML: {e}")
        
        # 尝试查找推文元素（根据X网站的最新结构）
        tweet_selectors = [
            'article[data-testid="tweet"]',
            'div[data-testid="tweet"]',
            'article',
            '.timeline-item'
        ]
        
        tweet_elements = []
        for selector in tweet_selectors:
            elements = response.html.find(selector)
            if elements:
                tweet_elements = elements
                logger.info(f"使用选择器 '{selector}' 找到 {len(elements)} 个推文元素")
                break
        
        if not tweet_elements:
            logger.warning("无法找到推文元素，尝试保存页面源码以供调试")
            with open(f"debug_{username}_page.html", "w", encoding="utf-8") as f:
                f.write(response.html.html)
            return []
            
        logger.info(f"找到 {len(tweet_elements)} 个可能的推文元素")
        
        for i, article in enumerate(tweet_elements):
            if i >= max_count:
                break
                
            try:
                # 尝试提取推文信息
                # 提取推文ID（从链接中）
                tweet_id = None
                link_elements = article.find('a')
                for link in link_elements:
                    href = link.attrs.get('href', '')
                    if '/status/' in href:
                        tweet_id = href.split('/status/')[1].split('?')[0]
                        break
                
                if not tweet_id:
                    continue
                
                # 提取推文内容
                content = ""
                content_selectors = [
                    'div[data-testid="tweetText"]',
                    'div[lang]', 
                    '.tweet-content'
                ]
                
                for selector in content_selectors:
                    elements = article.find(selector)
                    if elements:
                        content = elements[0].text
                        break
                
                # 提取媒体
                media = []
                img_selectors = [
                    'img[alt="Image"]',
                    'img[alt="嵌入的图片"]',
                    'img.media-img'
                ]
                
                for selector in img_selectors:
                    img_elements = article.find(selector)
                    if img_elements:
                        for img in img_elements:
                            if 'src' in img.attrs:
                                media.append({
                                    'type': 'photo',
                                    'url': img.attrs['src']
                                })
                        break
                
                # 创建时间（使用当前时间，因为难以准确提取）
                created_at = datetime.now().isoformat()
                
                tweet = {
                    'id': tweet_id,
                    'content': content,
                    'created_at': created_at,
                    'url': f"https://twitter.com/{username}/status/{tweet_id}",
                    'media': media
                }
                
                tweets.append(tweet)
                logger.info(f"已抓取推文 {tweet_id}")
                
            except Exception as e:
                logger.error(f"解析推文时出错: {e}")
                logger.debug(traceback.format_exc())
                continue
        
    except Exception as e:
        logger.error(f"直接抓取X网站失败: {e}")
        logger.debug(traceback.format_exc())
    
    session.close()
    return tweets

def save_cache_file(tweets, username):
    """保存推文到缓存文件"""
    try:
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'tweets': tweets
        }
        
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"已将 {len(tweets)} 条推文保存到缓存")
    except Exception as e:
        logger.error(f"保存推文到缓存时出错: {e}")
        logger.debug(traceback.format_exc())

def filter_new_tweets(tweets, processed_ids):
    """过滤出未处理过的新推文"""
    new_tweets = [tweet for tweet in tweets if tweet['id'] not in processed_ids]
    return new_tweets

def save_tweets_to_file(tweets, filename):
    """保存推文到文件"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(tweets, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存 {len(tweets)} 条推文到 {filename}")
    except Exception as e:
        logger.error(f"保存推文到文件时出错: {e}")
        logger.debug(traceback.format_exc())

def save_tweets_to_windows(tweets, username):
    """保存推文到Windows系统"""
    if not WINDOWS_SAVE_PATH:
        logger.info("未指定Windows保存路径，跳过保存到Windows系统")
        return False
    
    try:
        # 检查是否在WSL环境中
        is_wsl = "microsoft" in platform.uname().release.lower()
        
        if not is_wsl:
            logger.warning("当前不是WSL环境，无法使用/mnt路径保存到Windows，尝试直接保存")
            windows_path = WINDOWS_SAVE_PATH
        else:
            # 处理Windows路径
            # 如果提供的是Windows格式路径（如C:/Users/...），将其转换为WSL路径格式
            if ':' in WINDOWS_SAVE_PATH:
                # 从Windows路径格式（如C:/Users/username/Documents）转换为WSL格式
                drive_letter = WINDOWS_SAVE_PATH[0].lower()
                path_part = WINDOWS_SAVE_PATH[2:].replace('\\', '/')
                windows_path = f"/mnt/{drive_letter}/{path_part}"
            else:
                # 已经是WSL路径格式
                windows_path = WINDOWS_SAVE_PATH
        
        # 创建目标目录（如果不存在）
        os.makedirs(windows_path, exist_ok=True)
        
        # 生成文件名（使用日期和用户名）
        current_date = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{username}_tweets_{current_date}.json"
        full_path = os.path.join(windows_path, filename)
        
        # 保存推文到文件
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(tweets, f, ensure_ascii=False, indent=2)
            
        logger.info(f"已将 {len(tweets)} 条推文原文保存到Windows系统: {full_path}")
        return True
    except Exception as e:
        logger.error(f"保存推文到Windows系统时出错: {e}")
        logger.debug(traceback.format_exc())
        return False

def get_mock_tweets():
    """生成模拟推文数据用于测试"""
    logger.info("生成模拟推文数据用于测试")
    mock_tweets = []
    
    # 生成5条模拟推文
    for i in range(1, 6):
        tweet_id = f"12345678901234{i}"
        content = f"这是一条测试推文 #{i}，用于测试Windows保存功能。This is a test tweet #{i}."
        created_at = datetime.now().isoformat()
        media = []
        
        # 偶数推文添加媒体
        if i % 2 == 0:
            media.append({
                'type': 'photo',
                'url': 'https://pbs.twimg.com/media/sample_image.jpg'
            })
        
        tweet = {
            'id': tweet_id,
            'content': content,
            'created_at': created_at,
            'url': f"https://twitter.com/{USERNAME}/status/{tweet_id}",
            'media': media
        }
        
        mock_tweets.append(tweet)
    
    return mock_tweets

def main():
    """主函数"""
    logger.info(f"开始抓取 @{USERNAME} 的推文")
    
    # 检查缓存是否有效
    if is_valid_cache() and not args.force:
        logger.info("使用缓存数据")
        tweets = load_tweets_from_cache()
    else:
        # 尝试使用模拟数据（仅供测试Windows保存功能）
        if args.test and args.windows_path:
            logger.info("测试模式：使用模拟数据测试Windows保存功能")
            tweets = get_mock_tweets()
        else:
            # 先尝试从Nitter抓取
            tweets = scrape_tweets_from_nitter(USERNAME, MAX_TWEETS)
            
            # 如果Nitter抓取失败，尝试直接抓取
            if not tweets:
                logger.warning("从Nitter抓取失败，尝试直接抓取X网站")
                tweets = scrape_tweets_directly(USERNAME, MAX_TWEETS)
        
        # 如果抓取成功或使用了模拟数据，保存到缓存
        if tweets:
            save_cache_file(tweets, USERNAME)
        else:
            logger.error("抓取失败，未获取到任何推文")
            return
    
    # 加载已处理的推文ID
    processed_ids = load_processed_tweets()
    
    # 过滤出新推文
    new_tweets = filter_new_tweets(tweets, processed_ids)
    
    if new_tweets:
        logger.info(f"发现 {len(new_tweets)} 条新推文")
        # 保存新推文到输出文件
        save_tweets_to_file(new_tweets, OUTPUT_FILE)
        # 保存推文到Windows系统
        save_tweets_to_windows(new_tweets, USERNAME)
    else:
        logger.info("没有发现新推文")
        # 即使没有新推文，也保存所有已抓取推文到Windows系统
        if WINDOWS_SAVE_PATH:
            save_tweets_to_windows(tweets, USERNAME)
    
    logger.info("抓取完成")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序运行出错: {e}")
        logger.debug(traceback.format_exc()) 