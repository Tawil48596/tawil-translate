# Architecture

## 边界

项目采用 Ports & Adapters：`domain` 中的类型与协议不依赖 PySide6、音频库或模型 SDK；`application` 只负责调度；可替换实现放在 `infrastructure`；Qt 通过事件桥接器订阅输出。

## 并发与延迟策略

1. 音频回调只复制 PCM 到环形缓冲，不做 VAD 或推理。
2. VAD 输出经过智能断句后进入容量固定的 `asyncio.Queue`。
3. 队列满时上游等待，形成背压；后续可按延迟目标切换为“丢弃最旧片段”。
4. STT 与翻译产生领域事件，Qt 主线程只渲染事件。
5. 所有工作协程共享取消生命周期，退出时不会遗留录音设备或网络连接。

## 字幕一致性

每个语句分配稳定 `utterance_id`。STT 只有在提交后才进入翻译；翻译增量只能追加到同一 ID，最终事件将其锁定。这样底层 STT 的回溯不会重写用户已经读过的源字幕。

## 下一阶段

- Windows 10 2004+ 的 Process Loopback Capture 原生适配器
- Silero VAD 的预热与跨帧智能断句
- Faster-Whisper 单工作线程和显存自适应
- OpenAI-compatible SSE 客户端、超时/重试/熔断
- Qt 信号桥、描边文字、双模式与全局热键
- 模型下载器、签名安装器与 Windows 打包流水线

