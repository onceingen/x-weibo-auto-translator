# X to Weibo 推文自动翻译发布工具

这个项目是一个自动化工具，用于从 X（Twitter）抓取指定公众艺人的推文，使用 AI 工具将其翻译成简体中文，然后发布到微博平台上该艺人的账号。

## 功能特点

- 自动抓取指定 X 账号的最新推文
- 使用 OpenAI 的 GPT 模型翻译推文内容
- 智能识别日语和英语，采用不同的翻译策略
- 支持带图片的推文（最多支持 9 张图片）
- 自动发布到微博账号
- 记录已处理的推文，避免重复发布
- 支持测试模式，可以在不实际发布到微博的情况下测试功能
- 内置智能重试机制，处理 API 限制和网络错误
- 灵活的缓存系统，减少 API 调用次数
- 跳过转发类推文，专注于原创内容
- 自动备用翻译功能，当OpenAI配额不足时切换到免费翻译服务
- **智能API模式切换**：当X API速率限制触发时，自动切换为无API抓取模式

## 安装

1. 确保你安装了 Python 3.6+ 版本
2. 克隆此仓库到本地
3. 创建并激活虚拟环境：

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或者
venv\Scripts\activate  # Windows
```

4. 安装依赖：

```bash
pip install tweepy openai weibo tenacity requests-html
```

## 配置

1. 复制 `config.example.ini` 为 `config.ini`：

```bash
cp config.example.ini config.ini
```

2. 编辑 `config.ini` 文件，填入你的 API 密钥和设置：
   - X（Twitter）API 密钥和访问令牌
   - OpenAI API 密钥
   - 微博 API 密钥和访问令牌
   - 要抓取的艺人 X 用户名（不包含 @ 符号）
   - 测试模式设置（True/False）
   - 缓存过期时间（分钟）
   - 备用翻译设置

## 使用

### 基本用法

运行集成服务脚本：

```bash
python run_x_service.py
```

这将启动主服务，自动处理以下流程：
1. 尝试使用X API获取推文
2. 如果API速率受限，自动切换为无API抓取模式
3. 翻译获取到的推文
4. 发布到微博

### 命令行参数

服务脚本支持以下命令行参数：

- `--test`: 启用测试模式，不实际发布到微博
- `--username <n>`: 指定要抓取的X用户名，覆盖配置文件设置
- `--count <num>`: 指定要抓取的最大推文数量，默认为5
- `--interval <minutes>`: 设置检查间隔（分钟），默认为10分钟
- `--once`: 仅运行一次，不循环检查
- `--no-api`: 强制使用无API方式抓取，完全绕过X API
- `--windows-path <path>`: 指定Windows系统中保存推文原文的路径，例如"C:/Users/username/Documents"

### 将推文原文保存至Windows系统

如果你在WSL(Windows Subsystem for Linux)环境中运行本工具，可以使用`--windows-path`参数将抓取到的推文原文保存到Windows主机的指定目录中：

```bash
# 保存推文原文到Windows的Documents目录
python run_x_service.py --windows-path "C:/Users/username/Documents/tweets"

# 与其他参数一起使用
python run_x_service.py --test --once --windows-path "D:/twitter_backup"
```

该功能会自动：

- 将Windows格式路径转换为WSL可访问的路径格式
- 创建指定目录（如果不存在）
- 使用日期时间和用户名生成唯一文件名
- 根据抓取方式生成不同的文件名前缀：
  - API模式生成的文件名格式：`username_api_tweets_YYYYMMDD_HHMMSS.json`
  - 无API模式生成的文件名格式：`username_tweets_YYYYMMDD_HHMMSS.json`
- 保存完整的推文原文和媒体信息

即使没有新的推文需要处理，该功能也会保存所有已抓取的推文到指定位置，确保你有完整的推文备份。

### 单独运行tweet_to_weibo.py

你也可以单独运行推文处理脚本：

```bash
# 测试模式，抓取10条推文后退出
python tweet_to_weibo.py --test --once --count 10

# 使用不同的艺人账号，忽略缓存
python tweet_to_weibo.py --artist another_artist --force

# 后台运行
nohup python tweet_to_weibo.py &
```

## API模式切换机制

系统实现了智能的API模式切换机制，在遇到X API速率限制时能够自动适应：

1. **默认模式**：系统优先使用X API获取推文，这样可以获得更准确的推文数据和媒体内容
2. **速率限制检测**：当检测到X API返回429错误（Too Many Requests）时，系统会记录失败
3. **智能降级**：连续失败3次后，系统会自动切换到无API模式，使用网页抓取方式获取推文
4. **自动恢复**：系统会在1小时后尝试重新使用API模式，如果成功则继续使用API，否则保持无API模式
5. **强制无API模式**：可以通过`--no-api`参数强制系统始终使用无API模式

这种机制确保了系统在面对API限制时能够持续工作，同时在条件允许时自动恢复使用API以获得更好的数据质量。

## 错误处理

此工具内置了智能错误处理和重试机制：

- X API 速率限制：自动切换到无API抓取模式
- OpenAI API 配额不足：自动切换到备用翻译服务
- 网络错误：自动重试，最多 3 次
- 微博发布失败：自动重试，带指数退避

## 备用翻译服务

当 OpenAI API 配额不足或请求失败时，系统将自动切换到备用翻译服务：

- 在 `config.ini` 中设置 `USE_BACKUP_TRANSLATOR = True` 启用备用翻译
- 支持多种备用服务，默认使用 Google 翻译
- 免费且无需 API 密钥
- 可以通过 `test_translation.py` 脚本测试翻译服务

```bash
# 测试备用翻译功能
python test_translation.py --api free --jp
```

## 缓存机制

为减少 API 调用频率，脚本使用缓存机制：

- 默认缓存有效期为 15 分钟（可在配置文件中调整）
- 使用 `--force` 参数可忽略缓存，强制刷新
- 缓存保存在 `cache_<username>_tweets.json` 文件中

## 测试

在 `config.ini` 中将 `TEST_MODE` 设置为 `True` 或使用 `--test` 参数进入测试模式，此模式下：
- 脚本将尝试调用真实 API，但不会实际发布内容到微博
- 在控制台和日志中显示详细处理过程

## 日志

运行日志存储在以下文件中：
- `tweet_to_weibo.log` - 推文处理和发布日志
- `x_scraper.log` - 无API抓取日志
- `x_service.log` - 集成服务运行日志

## 许可

[在此添加许可信息]

## 注意事项

- 请确保遵守各平台的服务条款和 API 使用限制
- 注意 API 调用频率限制，避免因频繁请求被平台限制访问
- 定期检查日志文件，确保服务正常运行
- 备用翻译服务仅供学习和测试使用，请遵守相关服务条款 