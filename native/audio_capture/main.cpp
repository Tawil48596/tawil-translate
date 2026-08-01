#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <mmdeviceapi.h>
#include <objidl.h>
#include <propidl.h>
#include <wrl/client.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <new>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace {
constexpr uint32_t kSampleRate = 16000;
constexpr uint16_t kChannels = 1;
constexpr uint16_t kBitsPerSample = 16;
std::atomic_bool g_stop{false};

#pragma pack(push, 1)
struct FrameHeader {
    char magic[4];
    uint32_t payloadBytes;
    uint16_t channels;
    uint16_t sampleRate;
};
#pragma pack(pop)
static_assert(sizeof(FrameHeader) == 12);

void PrintError(const wchar_t* context, HRESULT hr) {
    wchar_t* message = nullptr;
    FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_ALLOCATE_BUFFER |
                       FORMAT_MESSAGE_IGNORE_INSERTS,
                   nullptr, static_cast<DWORD>(hr), 0, reinterpret_cast<wchar_t*>(&message), 0,
                   nullptr);
    fwprintf(stderr, L"%ls failed (0x%08lx): %ls\n", context,
             static_cast<unsigned long>(hr), message ? message : L"unknown error");
    if (message) LocalFree(message);
}

BOOL WINAPI ConsoleHandler(DWORD signal) {
    if (signal == CTRL_C_EVENT || signal == CTRL_BREAK_EVENT || signal == CTRL_CLOSE_EVENT) {
        g_stop.store(true);
        return TRUE;
    }
    return FALSE;
}

class ActivationHandler final : public IActivateAudioInterfaceCompletionHandler, public IAgileObject {
public:
    ActivationHandler() : completed_(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {}
    ~ActivationHandler() { if (completed_) CloseHandle(completed_); }

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** value) override {
        if (!value) return E_POINTER;
        *value = nullptr;
        if (iid == __uuidof(IUnknown) || iid == __uuidof(IActivateAudioInterfaceCompletionHandler)) {
            *value = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
        } else if (iid == __uuidof(IAgileObject)) {
            *value = static_cast<IAgileObject*>(this);
        } else {
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references_; }
    ULONG STDMETHODCALLTYPE Release() override {
        const ULONG value = --references_;
        if (!value) delete this;
        return value;
    }
    HRESULT STDMETHODCALLTYPE ActivateCompleted(IActivateAudioInterfaceAsyncOperation* operation) override {
        ComPtr<IUnknown> activated;
        result_ = operation->GetActivateResult(&activationResult_, &activated);
        if (SUCCEEDED(result_) && SUCCEEDED(activationResult_)) result_ = activated.As(&client_);
        SetEvent(completed_);
        return S_OK;
    }
    HRESULT Wait(ComPtr<IAudioClient>& client) {
        if (!completed_) return HRESULT_FROM_WIN32(GetLastError());
        WaitForSingleObject(completed_, INFINITE);
        if (FAILED(result_)) return result_;
        if (FAILED(activationResult_)) return activationResult_;
        client = client_;
        return client ? S_OK : E_NOINTERFACE;
    }

private:
    std::atomic<ULONG> references_{1};
    HANDLE completed_ = nullptr;
    HRESULT result_ = E_PENDING;
    HRESULT activationResult_ = E_PENDING;
    ComPtr<IAudioClient> client_;
};

HRESULT ActivateProcessLoopback(DWORD pid, bool includeTree, ComPtr<IAudioClient>& client) {
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = pid;
    params.ProcessLoopbackParams.ProcessLoopbackMode = includeTree
        ? PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
        : PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE;
    PROPVARIANT activation{};
    activation.vt = VT_BLOB;
    activation.blob.cbSize = sizeof(params);
    activation.blob.pBlobData = reinterpret_cast<BYTE*>(&params);

    auto* handler = new (std::nothrow) ActivationHandler();
    if (!handler) return E_OUTOFMEMORY;
    ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
    HRESULT hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
                                               __uuidof(IAudioClient), &activation, handler,
                                               &operation);
    if (SUCCEEDED(hr)) hr = handler->Wait(client);
    handler->Release();
    return hr;
}

bool WriteAll(HANDLE output, const void* data, DWORD size) {
    const auto* cursor = static_cast<const BYTE*>(data);
    while (size) {
        DWORD written = 0;
        if (!WriteFile(output, cursor, size, &written, nullptr) || !written) return false;
        cursor += written;
        size -= written;
    }
    return true;
}

bool EmitFrame(HANDLE output, const BYTE* pcm, uint32_t bytes) {
    FrameHeader header{{'T', 'W', 'P', 'C'}, bytes, kChannels,
                       static_cast<uint16_t>(kSampleRate)};
    return WriteAll(output, &header, sizeof(header)) && WriteAll(output, pcm, bytes);
}

HRESULT Capture(DWORD pid, bool includeTree, uint32_t frameMs) {
    ComPtr<IAudioClient> audioClient;
    HRESULT hr = ActivateProcessLoopback(pid, includeTree, audioClient);
    if (FAILED(hr)) return hr;

    WAVEFORMATEX format{};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = kChannels;
    format.nSamplesPerSec = kSampleRate;
    format.wBitsPerSample = kBitsPerSample;
    format.nBlockAlign = format.nChannels * format.wBitsPerSample / 8;
    format.nAvgBytesPerSec = format.nSamplesPerSec * format.nBlockAlign;

    HANDLE ready = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!ready) return HRESULT_FROM_WIN32(GetLastError());
    hr = audioClient->Initialize(
        AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
            AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
        0, 0, &format, nullptr);
    if (SUCCEEDED(hr)) hr = audioClient->SetEventHandle(ready);
    ComPtr<IAudioCaptureClient> captureClient;
    if (SUCCEEDED(hr)) hr = audioClient->GetService(IID_PPV_ARGS(&captureClient));
    if (SUCCEEDED(hr)) hr = audioClient->Start();
    if (FAILED(hr)) { CloseHandle(ready); return hr; }

    const uint32_t targetBytes = kSampleRate * format.nBlockAlign * frameMs / 1000;
    std::vector<BYTE> pending;
    pending.reserve(targetBytes * 2);
    HANDLE output = GetStdHandle(STD_OUTPUT_HANDLE);
    bool pipeOpen = true;

    while (!g_stop.load() && pipeOpen) {
        const DWORD wait = WaitForSingleObject(ready, 250);
        if (wait != WAIT_OBJECT_0 && wait != WAIT_TIMEOUT) {
            hr = HRESULT_FROM_WIN32(GetLastError());
            break;
        }
        UINT32 available = 0;
        while (SUCCEEDED(hr = captureClient->GetNextPacketSize(&available)) && available) {
            BYTE* data = nullptr;
            UINT32 frames = 0;
            DWORD flags = 0;
            hr = captureClient->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
            if (FAILED(hr)) break;
            const size_t bytes = static_cast<size_t>(frames) * format.nBlockAlign;
            const size_t offset = pending.size();
            pending.resize(offset + bytes);
            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) SecureZeroMemory(pending.data() + offset, bytes);
            else memcpy(pending.data() + offset, data, bytes);
            captureClient->ReleaseBuffer(frames);

            size_t consumed = 0;
            while (pending.size() - consumed >= targetBytes) {
                if (!EmitFrame(output, pending.data() + consumed, targetBytes)) {
                    pipeOpen = false;
                    break;
                }
                consumed += targetBytes;
            }
            if (consumed) pending.erase(pending.begin(), pending.begin() + consumed);
        }
        if (FAILED(hr)) break;
    }
    audioClient->Stop();
    CloseHandle(ready);
    return pipeOpen ? hr : S_OK;
}

void Usage() {
    fwprintf(stderr, L"Usage: tawil-audio-capture --pid PID [--include-tree|--exclude-tree] [--frame-ms 10..100]\n");
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
    DWORD pid = 0;
    bool includeTree = true;
    uint32_t frameMs = 20;
    for (int i = 1; i < argc; ++i) {
        if (wcscmp(argv[i], L"--pid") == 0 && i + 1 < argc) pid = wcstoul(argv[++i], nullptr, 10);
        else if (wcscmp(argv[i], L"--include-tree") == 0) includeTree = true;
        else if (wcscmp(argv[i], L"--exclude-tree") == 0) includeTree = false;
        else if (wcscmp(argv[i], L"--frame-ms") == 0 && i + 1 < argc) frameMs = wcstoul(argv[++i], nullptr, 10);
        else { Usage(); return 2; }
    }
    if (!pid || frameMs < 10 || frameMs > 100) { Usage(); return 2; }
    SetConsoleCtrlHandler(ConsoleHandler, TRUE);
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_HIGHEST);
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) { PrintError(L"CoInitializeEx", hr); return 3; }
    hr = Capture(pid, includeTree, frameMs);
    if (FAILED(hr)) PrintError(L"Process loopback capture", hr);
    CoUninitialize();
    return FAILED(hr) ? 4 : 0;
}
