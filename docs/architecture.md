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

## 模块级优化决策

| 模块 | 延迟策略 | 使用体验策略 | 降级策略 |
|---|---|---|---|
| Audio | 20ms PCM 帧、回调零推理 | 记忆 PID、设备热插拔事件 | 捕获失败时灰色状态灯 |
| VAD | 帧级判定、280ms 尾静音 | 自动合并口吃/短停顿 | Energy VAD 可零下载运行 |
| Chunker | 8 秒硬上限 | 保留完整短句上下文 | 超长语音及时切片送显 |
| STT | 模型预热、后台单实例 | 四档模型、一处切换 | CUDA 失败可切 CPU/int8 |
| LLM | SSE、短上下文、低温度 | 词库与目标语言统一配置 | 超时、熔断、不弹阻塞框 |
| Pipeline | 有界队列 | “低延迟/不丢句”策略可选 | 默认丢最旧避免字幕追赶 |
| Overlay | 原生绘制、局部更新 | 描边、淡入、双语与穿透 | 状态事件不遮挡游戏 |

## 统一程序组合

`bootstrap.py` 是唯一入口。`--desktop` 启动设置与悬浮窗，`--list-models` 展示模型档位，`--profile` 可脚本化切换，`--demo` 用于无模型诊断。桌面设置保存到被 Git 忽略的 `configs/user_config.json`，API Key 仍只从环境变量读取。

## Native capture boundary

Process loopback requires Windows build 20348+ and `ActivateAudioInterfaceAsync` with the virtual process-loopback device. A small x64 native helper owns COM and WASAPI, includes the selected PID's process tree, and sends framed PCM16 to Python. The helper never writes logs to stdout. Python validates magic, frame length, sample rate and exit status before admitting frames to VAD.

This boundary is intentional: implementing the completion-handler COM object through `ctypes` would make lifetime and callback failures capable of taking down the UI process. An isolated helper is easier to package, test and restart.
