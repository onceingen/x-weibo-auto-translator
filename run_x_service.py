#!/usr/bin/env python3

# 集成脚本：使用无API方式抓取X推文，然后交给tweet_to_weibo.py处理和发布
# 每10分钟检查一次新推文

import os
import sys
import time
import json
import logging
import argparse
import subprocess
import configparser
from datetime import datetime, timedelta

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("x_service.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("XService")

# 解析命令行参数
parser = argparse.ArgumentParser(description='抓取推文并发布到微博（自动切换API和无API模式）')
parser.add_argument('--username', type=str, help='要抓取的X用户名（不含@符号）')
parser.add_argument('--interval', type=int, default=10, help='检查间隔（分钟）')
parser.add_argument('--count', type=int, default=5, help='每次抓取的最大推文数量')
parser.add_argument('--test', action='store_true', help='测试模式，不实际发布到微博')
parser.add_argument('--once', action='store_true', help='仅运行一次，不循环检查')
parser.add_argument('--no-api', action='store_true', help='强制使用无API方式抓取推文')
parser.add_argument('--windows-path', type=str, help='Windows系统保存路径，用于保存推文原文')
args = parser.parse_args()

# 读取配置文件
config = configparser.ConfigParser()
config_file = 'config.ini'

if os.path.exists(config_file):
    config.read(config_file)
else:
    logger.warning(f"找不到配置文件 {config_file}，使用默认设置")

# API模式状态跟踪
USE_API_MODE = not args.no_api  # 默认使用API模式，除非指定--no-api

# 从配置文件读取API切换设置
ENABLE_AUTO_SWITCH = True  # 默认启用自动切换
if 'API_SWITCH' in config and 'ENABLE_AUTO_SWITCH' in config['API_SWITCH']:
    ENABLE_AUTO_SWITCH = config['API_SWITCH'].getboolean('ENABLE_AUTO_SWITCH')

API_FAILURE_COUNT = 0  # 记录API失败次数
MAX_API_FAILURES = 3  # 连续失败多少次后切换到无API模式
if 'API_SWITCH' in config and 'MAX_API_FAILURES' in config['API_SWITCH']:
    MAX_API_FAILURES = config['API_SWITCH'].getint('MAX_API_FAILURES')

API_RECOVERY_MINUTES = 60  # API恢复尝试时间（分钟）
if 'API_SWITCH' in config and 'API_RECOVERY_MINUTES' in config['API_SWITCH']:
    API_RECOVERY_MINUTES = config['API_SWITCH'].getint('API_RECOVERY_MINUTES')

LAST_API_FAILURE = None  # 最后一次API失败的时间

def run_scraper():
    """运行推文抓取器"""
    global USE_API_MODE, API_FAILURE_COUNT, LAST_API_FAILURE
    
    # 如果禁用了自动切换，并且是无API模式，则直接使用无API模式
    if not ENABLE_AUTO_SWITCH and args.no_api:
        USE_API_MODE = False
    
    # 检查是否需要尝试恢复API模式
    current_time = datetime.now()
    if not USE_API_MODE and LAST_API_FAILURE and ENABLE_AUTO_SWITCH:
        # 如果上次API失败已经超过设定的恢复时间，尝试重新使用API
        recovery_seconds = API_RECOVERY_MINUTES * 60
        if (current_time - LAST_API_FAILURE).total_seconds() > recovery_seconds:
            logger.info(f"自上次API失败已超过{API_RECOVERY_MINUTES}分钟，尝试重新使用API模式")
            USE_API_MODE = True
            API_FAILURE_COUNT = 0
    
    # 根据当前模式运行不同的抓取方式
    if USE_API_MODE:
        logger.info("使用X API模式抓取推文...")
        # 直接调用tweet_to_weibo.py，让它自动处理API逻辑
        cmd = [sys.executable, 'tweet_to_weibo.py', '--force', '--once']
        
        if args.username:
            cmd.extend(['--artist', args.username])
        if args.count:
            cmd.extend(['--count', str(args.count)])
        if args.test:
            cmd.append('--test')
        # 添加Windows路径参数
        if args.windows_path:
            cmd.extend(['--windows-path', args.windows_path])
            
        try:
            logger.info(f"执行命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # 检查是否出现API错误
            if result.returncode != 0 or "X API请求次数超过限制" in result.stdout or "X API请求次数超过限制" in result.stderr:
                API_FAILURE_COUNT += 1
                LAST_API_FAILURE = current_time
                logger.warning(f"API模式失败 ({API_FAILURE_COUNT}/{MAX_API_FAILURES}): {result.stderr}")
                
                # 如果连续失败次数达到阈值，切换到无API模式
                if API_FAILURE_COUNT >= MAX_API_FAILURES:
                    logger.warning(f"连续{MAX_API_FAILURES}次API失败，切换到无API模式")
                    USE_API_MODE = False
                    # 立即使用无API模式重试
                    return run_scraper()
                    
                return False
            
            # API成功，重置失败计数
            API_FAILURE_COUNT = 0
            logger.info("API模式抓取成功完成")
            return True
            
        except Exception as e:
            API_FAILURE_COUNT += 1
            LAST_API_FAILURE = current_time
            logger.error(f"运行API模式抓取器时出错: {e}")
            
            # 如果连续失败次数达到阈值，切换到无API模式
            if API_FAILURE_COUNT >= MAX_API_FAILURES:
                logger.warning(f"连续{MAX_API_FAILURES}次API失败，切换到无API模式")
                USE_API_MODE = False
                # 立即使用无API模式重试
                return run_scraper()
                
            return False
    else:
        # 无API模式
        logger.info("使用无API模式抓取推文...")
        cmd = [sys.executable, 'x_scraper.py', '--once', '--force']
        
        if args.username:
            cmd.extend(['--username', args.username])
        if args.count:
            cmd.extend(['--count', str(args.count)])
        # 添加Windows路径参数
        if args.windows_path:
            cmd.extend(['--windows-path', args.windows_path])
        # 添加测试模式参数
        if args.test:
            cmd.append('--test')
        
        try:
            logger.info(f"执行命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"无API抓取失败: {result.stderr}")
                return False
                
            logger.info("无API模式抓取成功完成")
            return True
        except Exception as e:
            logger.error(f"运行无API抓取器时出错: {e}")
            return False

def run_tweet_processor():
    """运行推文处理器（翻译和发布）"""
    # 如果是无API模式，需要单独运行处理器
    if not USE_API_MODE:
        logger.info("运行推文处理器...")
        
        cmd = [sys.executable, 'tweet_to_weibo.py', '--once', '--force']
        
        if args.username:
            cmd.extend(['--artist', args.username])
        if args.test:
            cmd.append('--test')
        # 添加Windows路径参数
        if args.windows_path:
            cmd.extend(['--windows-path', args.windows_path])
        
        try:
            logger.info(f"执行命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"处理推文失败: {result.stderr}")
                return False
                
            logger.info("推文处理成功完成")
            return True
        except Exception as e:
            logger.error(f"运行处理器时出错: {e}")
            return False
    else:
        # API模式下已经在run_scraper中处理了
        return True

def check_config():
    """检查配置文件和依赖是否已准备好"""
    # 打印调试信息
    logger.info(f"[DEBUG] sys.executable: {sys.executable}")
    logger.info(f"[DEBUG] sys.path: {sys.path}")
    
    # 检查配置文件
    if not os.path.exists('config.ini'):
        logger.error("找不到config.ini文件，请先配置")
        return False
        
    # 检查必要的脚本文件
    if not os.path.exists('x_scraper.py'):
        logger.error("找不到x_scraper.py文件")
        return False
        
    if not os.path.exists('tweet_to_weibo.py'):
        logger.error("找不到tweet_to_weibo.py文件")
        return False
    
    # 检查 requests-html 库是否已安装
    try:
        import importlib
        logger.info("[DEBUG] Attempting to import 'requests_html'")
        importlib.import_module('requests_html')
        logger.info("[DEBUG] 'requests_html' imported successfully")
    except ImportError as e:
        logger.error(f"[DEBUG] ImportError: {e}")
        logger.error("未安装requests-html库，请先安装: pip install requests-html")
        return False
    
    return True

def main():
    """主函数"""
    global USE_API_MODE
    
    logger.info("=== X推文抓取和发布服务开始运行 ===")
    
    # 检查配置和依赖
    if not check_config():
        logger.error("配置检查失败，程序退出")
        sys.exit(1)
    
    # 显示运行模式
    mode = "测试模式" if args.test else "正常模式"
    api_mode = "强制无API模式" if args.no_api else ("智能API/无API切换模式" if ENABLE_AUTO_SWITCH else "API模式")
    interval = args.interval
    logger.info(f"运行模式: {mode}, API模式: {api_mode}, 检查间隔: {interval}分钟")
    logger.info(f"API切换设置: 启用={ENABLE_AUTO_SWITCH}, 最大失败次数={MAX_API_FAILURES}, 恢复时间={API_RECOVERY_MINUTES}分钟")
    
    # 显示Windows保存路径信息
    if args.windows_path:
        logger.info(f"推文原文将保存到Windows路径: {args.windows_path}")
    
    # 仅运行一次或循环运行
    try:
        while True:
            # 运行抓取器
            if run_scraper():
                # 如果抓取成功，运行处理器
                run_tweet_processor()
            
            # 如果只运行一次就退出
            if args.once:
                logger.info("仅运行一次模式，程序结束")
                break
                
            # 等待下一次检查
            next_check = datetime.now() + timedelta(minutes=interval)
            logger.info(f"下一次检查时间: {next_check.strftime('%Y-%m-%d %H:%M:%S')}, 使用{'API' if USE_API_MODE else '无API'}模式")
            time.sleep(interval * 60)
            
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序运行出错: {e}")
        
if __name__ == "__main__":
    main() 