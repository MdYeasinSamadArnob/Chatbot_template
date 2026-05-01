# BA Smart Assistant — Mobile Integration Guide

This document describes how a native Android/iOS app (or React Native shell) should open
the bot WebView with a verified user identity, enable session persistence, and support the
"Continue from last chat" feature.

---

## 1. Architecture Overview

```
Mobile App ──── HTTPS ────► bot-ui (Next.js :3001)
                               │
                               │ Socket.IO ws
                               ▼
                          bot-socket (FastAPI :9001)
                               │
                        ┌──────┴──────┐
                        ▼             ▼
                   PostgreSQL        Redis
                (source of truth)  (session cache)
```

The mobile app **signs** the user identity with HMAC-SHA256 and passes it as URL query
parameters.  The backend verifies the signature before trusting any identity claim.

---

## 2. WebView URL Format

```
https://<bot-ui-host>/?user_id=<id>&username=<name>&screen_context=<ctx>&timestamp=<unix>&signature=<hmac>
```

**On page reload** (user presses refresh inside WebView), the frontend appends
`conversation_id` from `localStorage` automatically — the app does **not** need to manage
`conversation_id`.

### Parameters

| Parameter        | Type   | Max length | Allowed characters            | Required |
|------------------|--------|-----------|-------------------------------|----------|
| `user_id`        | string | 128        | `a-z A-Z 0-9 - _ . @`        | Yes (authenticated) |
| `username`       | string | 50         | `a-z A-Z 0-9 space`           | Yes (authenticated) |
| `screen_context` | string | 64         | `a-z A-Z 0-9 _`               | No       |
| `timestamp`      | string | —          | Unix epoch seconds (integer)  | Yes (authenticated) |
| `signature`      | string | —          | Lowercase hex HMAC-SHA256     | Yes (authenticated) |

### Screen context values

| Value           | Contextualised quick-action chips |
|-----------------|-----------------------------------|
| `transfer`      | Transfer money, Transfer limits, International transfer, Add beneficiary |
| `balance_check` | Check balance, Mini statement, View transactions, Account details |
| `card_services` | Block card, Card activation, Card limit, Replace card |
| `loans`         | Loan eligibility, Apply for loan, EMI calculator, Loan status |
| *(omitted)*     | Default banking chips |

---

## 3. HMAC Signature Generation

### Algorithm

```
payload   = "{user_id}:{username}:{screen_context}:{timestamp}"
signature = HMAC-SHA256(key=SESSION_SECRET, msg=payload).hexdigest()
```

> **Important:** Use the **raw** (not URL-encoded) values when constructing the payload
> string.  URL-encode the values **after** computing the signature.

Clock skew tolerance is ±120 seconds.  Always use the current device time.

---

### Android / Kotlin

```kotlin
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

fun generateBotUrl(
    userId: String,
    username: String,
    screenContext: String,
    secret: String,
    baseUrl: String = "https://your-bot-ui-host"
): String {
    val timestamp = System.currentTimeMillis() / 1000
    val payload = "$userId:$username:$screenContext:$timestamp"

    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
    val signature = mac.doFinal(payload.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }

    return buildString {
        append(baseUrl)
        append("/?user_id=").append(Uri.encode(userId))
        append("&username=").append(Uri.encode(username))
        append("&screen_context=").append(Uri.encode(screenContext))
        append("&timestamp=").append(timestamp)
        append("&signature=").append(signature)
    }
}
```

---

### iOS / Swift

```swift
import CryptoKit
import Foundation

func generateBotUrl(
    userId: String,
    username: String,
    screenContext: String,
    secret: String,
    baseUrl: String = "https://your-bot-ui-host"
) -> URL? {
    let timestamp = Int(Date().timeIntervalSince1970)
    let payload = "\(userId):\(username):\(screenContext):\(timestamp)"

    let keyData = Data(secret.utf8)
    let msgData = Data(payload.utf8)
    let mac = HMAC<SHA256>.authenticationCode(for: msgData, using: SymmetricKey(data: keyData))
    let signature = mac.map { String(format: "%02x", $0) }.joined()

    var comps = URLComponents(string: baseUrl)!
    comps.queryItems = [
        URLQueryItem(name: "user_id",        value: userId),
        URLQueryItem(name: "username",       value: username),
        URLQueryItem(name: "screen_context", value: screenContext),
        URLQueryItem(name: "timestamp",      value: "\(timestamp)"),
        URLQueryItem(name: "signature",      value: signature),
    ]
    return comps.url
}
```

---

### React Native

```typescript
import { createHmac } from "crypto";  // Node polyfill via react-native-crypto

export function generateBotUrl(
  userId: string,
  username: string,
  screenContext: string,
  secret: string,
  baseUrl = "https://your-bot-ui-host"
): string {
  const timestamp = Math.floor(Date.now() / 1000);
  const payload = `${userId}:${username}:${screenContext}:${timestamp}`;
  const signature = createHmac("sha256", secret).update(payload).digest("hex");

  const params = new URLSearchParams({
    user_id: userId,
    username,
    screen_context: screenContext,
    timestamp: String(timestamp),
    signature,
  });
  return `${baseUrl}/?${params.toString()}`;
}
```

> For React Native, add `react-native-crypto` + `react-native-randombytes` and configure
> your Metro bundler to shim the Node `crypto` module.

---

## 4. Session Flow

### 4a. Fresh WebView launch (first ever visit)

```
App opens WebView ──► bot-ui loads (no localStorage for this user)
                         │
                         │  Socket connect with all 5 identity params
                         ▼
                    backend creates new conversation
                         │  emits user_context { has_previous_session: false }
                         ▼
                    UI shows empty state (default/contextual chips)
```

### 4b. User closes & re-opens WebView

```
App opens WebView ──► bot-ui loads
                         │  reads localStorage: ba_conv_id:{user_id} = "prev-conv-uuid"
                         │  Socket connect with conversation_id = "prev-conv-uuid"
                         ▼
                    backend verifies ownership, loads session from Redis/DB
                         │  emits history { messages: [...] }
                         ▼
                    UI replays previous messages — user continues seamlessly
```

### 4c. Fresh launch with previous history — "Continue from last chat"

```
App opens WebView (e.g. from push notification, no localStorage)
                         │  Socket connect WITHOUT conversation_id
                         ▼
                    backend creates NEW conversation
                    detects user has prior conversations
                         │  emits user_context { has_previous_session: true, prev_conv_id: "..." }
                         ▼
                    UI shows "Continue from last chat" button
                         │  user taps button
                         ▼
                    frontend emits load_previous_session { prev_conv_id }
                         ▼
                    backend verifies ownership, loads last 50 msgs
                         │  emits history_payload { messages: [...] }
                         ▼
                    UI replaces message list (does NOT append)
```

---

## 5. localStorage Key

The frontend stores the active conversation ID with a per-user key:

```
localStorage key:  ba_conv_id:{user_id}
localStorage value: <UUID>
```

This means multiple users on the same device never share session data.
Guests (unauthenticated) do not have a persistent key.

---

## 6. Guest Mode

Omit all five identity parameters to open the bot as a guest:

```
https://<bot-ui-host>/
```

Guests:
- Get a fresh ephemeral conversation UUID on every connect
- Cannot access previous sessions
- See default quick-action chips
- Are not stored in the user→conv Redis mapping

---

## 7. Backend Configuration

### `.env` (bot-socket)

```env
# Required — must be 32+ random bytes, base64 or hex encoded
SESSION_SECRET=change_me_to_a_long_random_secret_minimum_32_chars

# Optional Redis — omit to run without cache (PostgreSQL only)
REDIS_URL=redis://10.11.200.99:6379/0
```

### Rotating `SESSION_SECRET`

1. Generate a new secret: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Deploy the new value.
3. All in-flight WebView sessions will re-authenticate on next connection (clock-skew
   rejection will cause a clean disconnect + reconnect with the new signature from the app).
4. Ensure the mobile app receives the new secret from your key-management system before
   the rotation takes effect.

---

## 8. Security Notes

- HMAC signatures are **single-use** within the ±120-second window but are not stored for
  replay detection.  For higher-security deployments, add a nonce and a server-side used-nonce
  set in Redis with a 5-minute TTL.
- `user_id`, `username`, and `screen_context` are sanitized server-side regardless of what
  the client sends — injection is not possible.
- The `username` is further stripped to first-name only before inclusion in LLM prompts.
- Redis is a cache only.  All identity data is authoritative from PostgreSQL.
