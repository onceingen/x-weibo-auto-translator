# X to Weibo 推文自动翻译发布工具

这个项目是一个自动化工具，用于从 X（Twitter）抓取指定公众艺人的推文，使用 AI 工具将其翻译成简体中文，然后发布到微博平台上该艺人的账号。

## 功能特点

- 自动抓取指定 X 账号的最新推文
- 使用 OpenAI 的 GPT 模型翻译推文内容
- 支持带图片的推文（最多支持 9 张图片）
- 自动发布到微博账号
- 记录已处理的推文，避免重复发布
- 支持测试模式，可以在不实际发布到微博的情况下测试功能

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
pip install tweepy openai weibo
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

## 使用

1. 确保配置文件已正确设置
2. 运行脚本：

```bash
python tweet_to_weibo.py
```

3. 如果要在后台持续运行，可以使用：

```bash
nohup python tweet_to_weibo.py &
```

## 测试

在 `config.ini` 中将 `TEST_MODE` 设置为 `True` 可以进入测试模式，此模式下：
- 脚本将使用模拟数据而不是实际调用 X API
- 不会调用 OpenAI API 进行翻译
- 不会实际发布内容到微博
- 仅在控制台和日志中显示处理过程

## 日志

运行日志存储在 `tweet_to_weibo.log` 文件中，包含详细的运行信息、错误和警告。

## 许可

[在此添加许可信息]

## 注意事项

- 请确保遵守各平台的服务条款和 API 使用限制
- 注意 API 调用频率限制，避免因频繁请求被平台限制访问
- 定期检查日志文件，确保服务正常运行 