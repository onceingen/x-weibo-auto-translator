#!/usr/bin/env python3

# 简单测试脚本：从X获取@syope的推文并翻译 (使用 X API v2 和 Bearer Token)

import tweepy
import openai
import urllib.parse
from configparser import ConfigParser

# 读取配置
config = ConfigParser()
config.read('config.ini')

# X API配置
X_API_KEY = config['API_KEYS']['X_API_KEY']
X_API_SECRET = config['API_KEYS']['X_API_SECRET']
X_ACCESS_TOKEN = config['API_KEYS']['X_ACCESS_TOKEN']
X_ACCESS_TOKEN_SECRET = config['API_KEYS']['X_ACCESS_TOKEN_SECRET']
X_BEARER_TOKEN = config['API_KEYS']['X_BEARER_TOKEN']

# % 被转义为 %% 读取时需要还原
X_BEARER_TOKEN = X_BEARER_TOKEN.replace('%%', '%')

# 打印凭证长度用于验证（不打印实际内容以保护安全）
print(f"API KEY 长度: {len(X_API_KEY)}")
print(f"API SECRET 长度: {len(X_API_SECRET)}")
print(f"ACCESS TOKEN 长度: {len(X_ACCESS_TOKEN)}")
print(f"ACCESS TOKEN SECRET 长度: {len(X_ACCESS_TOKEN_SECRET)}")
print(f"BEARER TOKEN 长度: {len(X_BEARER_TOKEN)}")

# OpenAI配置
OPENAI_API_KEY = config['OPENAI']['OPENAI_API_KEY']

# 要获取的用户
username = config['SETTINGS']['X_USERNAME']  # 应该是 "syope"

print(f"\n开始测试：获取 @{username} 的最新推文并翻译 (使用 Bearer Token)")

# 1. 获取推文 (使用 X API v2 + Bearer Token)
try:
    print("正在创建 X API v2 客户端（使用 Bearer Token）...")
    # 使用 Bearer Token 创建客户端
    client = tweepy.Client(bearer_token=X_BEARER_TOKEN)
    
    # 首先获取用户 ID
    print(f"正在查找用户 @{username}...")
    user = client.get_user(username=username)
    
    if user.data:
        user_id = user.data.id
        print(f"用户 ID: {user_id}")
        
        # 获取用户推文
        print(f"正在获取推文...")
        tweets = client.get_users_tweets(
            id=user_id,
            max_results=5,
            tweet_fields=['created_at', 'text']
        )
        
        if tweets.data:
            print(f"获取到 {len(tweets.data)} 条推文")
            
            # 2. 翻译推文
            for tweet in tweets.data:
                print("\n" + "="*50)
                print(f"推文ID: {tweet.id}")
                print(f"发布时间: {tweet.created_at}")
                print(f"原文: {tweet.text}")
                
                try:
                    print("正在翻译...")
                    openai.api_key = OPENAI_API_KEY
                    
                    response = openai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": "你是一位优秀的翻译，能够将文本准确地翻译成简体中文，同时保持原文的风格和感情。"},
                            {"role": "user", "content": f"请将以下文本翻译成简体中文:\n\n{tweet.text}"}
                        ]
                    )
                    
                    translated_text = response.choices[0].message.content.strip()
                    print(f"翻译结果: {translated_text}")
                    
                except Exception as e:
                    print(f"翻译出错: {e}")
        else:
            print(f"未找到推文")
    else:
        print(f"未找到用户 @{username}")
    
except Exception as e:
    print(f"获取推文出错: {e}")

print("\n测试完成") 