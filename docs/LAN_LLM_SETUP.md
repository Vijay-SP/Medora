# Shared Ollama server: Mac + backend PC + frontend PC

Configured 26 September 2026. Ollama is running at `http://Hisbaans-Mac-mini.local:11434`.
This guide uses the existing application and its native Ollama client.

Share the [teammate connection prompt](TEAMMATE_CONNECTION_PROMPT.md) for guided client setup.

## Addresses and resource ownership

```text
Browser -> frontend PC:5173 -> backend PC:8000 -> Mac:11434
           React / Vite      FastAPI            Ollama / Qwen3
```

| Setting | Value |
|---|---|
| Model host | Apple M4 Mac mini, 16 GB unified memory |
| Current Wi-Fi address (fallback only) | `192.168.178.115` (`en1`); may change |
| Ollama base URL | `http://Hisbaans-Mac-mini.local:11434` |
| Model name for this project | `medpark-extractor` |
| Base model | `hf.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF:Q4_K_M` |
| Model configuration | [`deploy/ollama/Modelfile`](../deploy/ollama/Modelfile), 4,096-token context |

Only LLM extraction uses this Mac's GPU and memory. Audio normalization, Whisper transcription,
CAM++ speaker recognition, document generation, storage, and email remain on the backend PC.
Ollama does not expose the project's Whisper/CAM++ engines. Moving those engines here would
require a separate application change.

The existing `qwen2.5:7b` model is retained, but the backend should use `medpark-extractor`.
The optional 14B profile was not selected: this Mac has 16 GB shared between macOS and the GPU,
which is different from the documented server with 16 GB of dedicated GPU memory.

## 1. Check from another PC on the same Wi-Fi

Windows PowerShell:

```powershell
Test-NetConnection Hisbaans-Mac-mini.local -Port 11434
Invoke-RestMethod http://Hisbaans-Mac-mini.local:11434/api/version
(Invoke-RestMethod http://Hisbaans-Mac-mini.local:11434/api/tags).models.name

$body = @{
    model = 'medpark-extractor'
    messages = @(@{ role = 'user'; content = 'Reply with a JSON object containing ok: true.' })
    format = 'json'
    stream = $false
    options = @{ temperature = 0; num_predict = 64 }
} | ConvertTo-Json -Depth 5
(Invoke-RestMethod -Method Post -Uri http://Hisbaans-Mac-mini.local:11434/api/chat `
    -ContentType 'application/json' -Body $body -TimeoutSec 240).message.content
```

macOS/Linux:

```sh
curl --fail --max-time 5 http://Hisbaans-Mac-mini.local:11434/api/version
curl --fail --max-time 5 http://Hisbaans-Mac-mini.local:11434/api/tags
curl --fail --max-time 240 http://Hisbaans-Mac-mini.local:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"medpark-extractor","messages":[{"role":"user","content":"Reply with a JSON object containing ok: true."}],"format":"json","stream":false,"options":{"temperature":0,"num_predict":64}}'
```

No Ollama installation or model download is required on a client PC using the HTTP API.
If a client already has the Ollama CLI, it can also use:

```powershell
$env:OLLAMA_HOST = 'http://Hisbaans-Mac-mini.local:11434'
ollama run medpark-extractor
```

On macOS/Linux, use `export OLLAMA_HOST=http://Hisbaans-Mac-mini.local:11434` instead.

## 2. Configure the backend PC

In the repository-root `.env` **on the backend PC**, add or update these entries, preserving
its other settings. Start the backend from that repository root so `.env` is found.

```dotenv
LLM_PROVIDER=ollama
LLM_API_BASE_URL=http://Hisbaans-Mac-mini.local:11434
LLM_MODEL_NAME=medpark-extractor
LLM_CONTEXT_TOKENS=4096
LLM_REQUEST_TIMEOUT_S=240
LLM_HEALTH_TIMEOUT_S=3
LLM_KEEP_ALIVE=10m
REQUIRE_LOCAL_LLM=true
LLM_FALLBACK_MODE=fail
```

Use the base URL exactly as shown; do not append `/v1`, `/api`, or `/api/chat`.
`REQUIRE_LOCAL_LLM=true` also works with a LAN Ollama server: it requires the configured
server/model to be available, not a loopback address.

For initial checks, keep email disconnected:

```dotenv
SMTP_HOST=127.0.0.1
SMTP_PORT=9
ALLOW_SIMULATED_DELIVERY=false
DELIVERY_CHANNEL=smtp
N8N_ENABLED=false
```

Create meetings in **supervised** mode. Do not use `auto_pilot` or the speed benchmark for
connection checks. The initial checks need no recordings or hospital email.

Start your already-installed backend environment:

```powershell
# Windows, from the repository root
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

```sh
# macOS/Linux, from the repository root
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

Find the backend PC's Wi-Fi IPv4 address with `ipconfig` on Windows (or its network settings).
Allow incoming TCP 8000 on its private LAN firewall profile. From the frontend PC, open
`http://BACKEND_PC_IP:8000/ready`: `llm_service.connected` should be `true` and its endpoint
should be this Mac. Overall readiness can still fail for missing ASR/voice models or the
deliberately disconnected SMTP server. `loaded=false` alone is normal between meetings.

If using Docker Compose instead, the existing compose file does not forward the root `.env`
LLM settings into the container. Add these entries to `medpark-app.environment` in
`deploy/docker-compose.yml` before recreating that service:

```yaml
      - LLM_PROVIDER=ollama
      - LLM_API_BASE_URL=http://Hisbaans-Mac-mini.local:11434
      - LLM_MODEL_NAME=medpark-extractor
      - REQUIRE_LOCAL_LLM=true
      - LLM_FALLBACK_MODE=fail
```

A Docker container must resolve the `.local` hostname **inside the container**; host resolution
alone is insufficient. If it cannot, use the stable router DNS/DHCP approach in section 4.

The backend PC still needs its own ASR/speaker models and the hardware configuration described
in the project README. Ollama on this Mac does not change those requirements.

## 3. Run the frontend on a separate PC

The frontend currently uses relative URLs such as `/api/v1`, `/health`, and `/ready`.
There is no `VITE_API_URL` setting in the current client. Route those paths through the
frontend's server to the backend PC.

On the **frontend PC**, edit `frontend/vite.config.ts`: replace **all three** occurrences of
`http://127.0.0.1:8000` with `http://BACKEND_PC_IP:8000`. Keep the `/api`, `/health`, and `/ready`
proxy entries. Then run:

```sh
cd frontend
npm ci
npm run dev -- --host 0.0.0.0
```

Windows can use `npm.cmd` if PowerShell blocks the npm script. Allow TCP 5173 on that PC's
private LAN firewall profile. Open `http://FRONTEND_PC_IP:5173` in a browser on the same LAN.
The proxy preserves same-origin browser requests, including uploads, audio and exports;
there is no need to broaden Ollama CORS or configure browsers to call Ollama directly.

Vite is for development. For a persistent frontend deployment, build with `npm run build`,
serve `frontend/dist` with a web server, and proxy `/api/`, `/health`, and `/ready` to
`http://BACKEND_PC_IP:8000`, preserving each request path. Configure an SPA fallback to
`index.html`, a suitable audio upload size limit, and upload timeouts. A plain static-file
server alone is insufficient because the app uses those relative API URLs.

## 4. Operate this Mac

Ollama runs natively for Apple GPU acceleration. The dedicated launch agent is
`~/Library/LaunchAgents/com.medpark.ollama-lan.plist`. The previous Homebrew launch agent is
disabled to prevent a second server from starting; its original file is preserved.

The service starts when user `hisbaan` logs in and restarts after a process failure.
It uses `caffeinate -i` to prevent **idle system sleep** while running; the display may sleep.
After a reboot, log in to this account. This is not a system service that starts before login,
and manually sleeping or shutting down the Mac interrupts inference.

Server settings: dynamic bind to the private IPv4 address of Wi-Fi interface `en1` on port 11434,
one parallel generation, at most one
loaded model, flash attention enabled, `q8_0` KV cache, ten-minute default keep-alive, cloud
features disabled. Other model names remain installed. Several PCs may connect, but generation
requests queue; this setup does not promise simultaneous full-speed meeting processing.
The application's explicit unload after each meeting still takes precedence over keep-alive.

```sh
# Run on this Mac
export OLLAMA_HOST=http://Hisbaans-Mac-mini.local:11434
ollama list
ollama ps
launchctl print gui/$(id -u)/com.medpark.ollama-lan
tail -n 50 "$HOME/Library/Logs/medpark-ollama.log"

# Restart (interrupts active requests)
launchctl kickstart -k gui/$(id -u)/com.medpark.ollama-lan

# Stop until explicitly started again or the next login
launchctl bootout gui/$(id -u)/com.medpark.ollama-lan

# Start after bootout (wait for the previous process to finish stopping)
while launchctl print gui/$(id -u)/com.medpark.ollama-lan >/dev/null 2>&1; do sleep 1; done
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.medpark.ollama-lan.plist"
```

The supervisor checks Wi-Fi every five seconds. It waits when there is no private IPv4 address,
starts Ollama when Wi-Fi returns, rebinds after an address change, and restarts a crashed child.
Six consecutive failed API health checks also trigger a restart (roughly 30–45 seconds).
Its installed copy is `~/Library/Application Support/Medpark/ollama_lan_supervisor.py`;
source and regression tests live under `deploy/scripts` and `deploy/tests`.

Use `Hisbaans-Mac-mini.local` on client PCs so their settings can survive IP changes. This is
macOS Bonjour/mDNS, which requires multicast name resolution on the client and LAN. Do not
rename the Mac's local hostname or hardcode its IP in a hosts file. The supervisor deliberately
binds only to the current Wi-Fi private IPv4 address, not VPN, public IPv6, or all interfaces.
It does not handle Ethernet-only connections; this installation watches `en1`.

While Wi-Fi is disconnected, the Mac is asleep/shut down, or clients are on a different LAN,
inference is unavailable. Existing requests can fail and do not resume automatically. Once
connectivity returns, verify `/api/version` and retry the failed request/meeting through the
normal supervised workflow. The service starts after login, not before login at boot.

If `.local` does not resolve on a teammate's PC (including some Windows or Docker setups),
enable working mDNS resolution there or ask the router administrator for a DHCP reservation
plus a stable LAN DNS record. Until then, obtain the current address on this Mac with
`ipconfig getifaddr en1` and use `http://CURRENT_IP:11434` temporarily. The initial address was
`192.168.178.115`; it is not a permanent fallback. A router reservation is recommended for
clients without mDNS but has not been configured by this setup.

To restore the previous localhost Homebrew service:

```sh
launchctl bootout gui/$(id -u)/com.medpark.ollama-lan
launchctl disable gui/$(id -u)/com.medpark.ollama-lan
launchctl enable gui/$(id -u)/homebrew.mxcl.ollama
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/homebrew.mxcl.ollama.plist"
```

## Connection troubleshooting

- If port 11434 times out, confirm the Mac is awake, the service is running, and the Wi-Fi
  hostname resolves to its current Wi-Fi address. Check guest Wi-Fi/client isolation and VPN LAN blocking.
- macOS Firewall was disabled during setup; no firewall policy was changed. If you enable it,
  allow incoming connections to the Ollama executable. Keep this unauthenticated HTTP API on
  a trusted LAN; do not port-forward 11434 on the router.
- If `/api/tags` works but the backend cannot connect, check the backend process environment,
  restart it after editing `.env`, and ensure a proxy is not intercepting private-IP traffic.
- If the UI cannot reach its API, check all three Vite proxy targets, restart Vite, and test
  port 8000 from the frontend PC. `localhost` always means the PC making that connection.
- If requests time out under load, process fewer meetings concurrently. Changing the client
  timeout does not increase this Mac's processing capacity.

## Verification

Verified locally on 26 September 2026:

- Existing Ollama `0.24.0` reused; base model downloaded and `medpark-extractor:latest` created
  from the checked-in Modelfile. Model manifest digest:
  `ed4bdb4dd8759a0e338aad87a181db4e9d6ffdabca4466928c840a85229dfb0f`.
- Schema-constrained `/api/chat` returned `{"ok": true}`. `ollama ps` reported **100% GPU**,
  **3.2 GB**, and a **4,096-token** context.
- `backend/tests/test_llm_extraction_live.py` **passed in 38.0 seconds** against localhost:
  11 synthetic transcript lines, two model calls, one decision, two actions, one risk,
  no failed chunks, no degraded fallback. Storage was isolated in a temporary directory;
  SMTP was disconnected and no email was sent. This does not benchmark a full recording.
- With explicit user approval, activated `com.medpark.ollama-lan` and disabled the previous
  Homebrew launch agent. Verified the listener is bound to `192.168.178.115:11434`, the native
  API responds there, the service is running, and macOS reports an idle-sleep prevention
  assertion owned by `caffeinate`. Service logs confirm cloud features are disabled.
- Re-ran `backend/tests/test_llm_extraction_live.py` through the initial `http://192.168.178.115:11434`:
  **passed in 46.8 seconds**, with the same decision/action/risk counts, no failed chunks,
  and no degraded fallback. GPU residency remained **100% GPU / 3.2 GB** during the test.
  The request originated on this Mac; a second-PC network check remains to be done.
- Added a supervisor that follows `en1` address changes. Four regression tests passed using
  real child processes with simulated network states: offline startup, same-IP reconnect,
  changed-IP reconnect, child crash, health-check recovery, and private-address validation.
  The actual Wi-Fi connection was not toggled during these tests.
- Stopped the real Ollama child deliberately while idle: the installed supervisor restarted
  it automatically and the hostname API responded again in **3.1 seconds**.
- The project's actual `OllamaClient` passed readiness and schema-constrained JSON inference
  through `Hisbaans-Mac-mini.local` (**4.6 seconds**, including model load). GPU residency was
  again **100% GPU / 3.2 GB**. Client-PC mDNS support still needs checking on each teammate's PC.

A successful request to the Mac's own Wi-Fi address does not prove another PC can cross its
Wi-Fi/firewall; run the commands in step 1 from that PC as the final network check.

References: [Ollama server configuration](https://docs.ollama.com/faq),
[native chat API](https://docs.ollama.com/api/chat),
[model listing](https://docs.ollama.com/api/tags),
[Apple local hostname documentation](https://support.apple.com/guide/mac-help/mchlp2322/mac).
