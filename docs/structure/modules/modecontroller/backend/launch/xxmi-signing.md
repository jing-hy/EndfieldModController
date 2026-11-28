---
uid: b1d0d003
id: modecontroller.backend.launch.xxmi-signing
parent: modecontroller.backend.launch
tags: [xxmi, signing]
name: {zh: "XXMI 签名密钥", en: "XXMI Signing Key"}
description:
  zh: >
      XXMI 会用自己的用户密钥给配置签名；签名缺失或过期时它会重置密钥并静默清空注入列表。由我们主动生成并写入密钥，才是注入列表不被它抹掉的根据。
      
  en: >
      XXMI signs its own settings with a user key; if that signature is absent or stale it regenerates the key and quietly wipes the injection list. Generating the key ourselves is what keeps our injections from being reset out from under us.
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.742Z"
fingerprint: 9c246c930949fd5474650274c14f7bcfbb9fbbd7f6e3357b7ba8f8d85b012462
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 1781
    end_line: 6343
apis:
  - protocol: rpc
    path: "ensure_xxmi_signing_key"
    description:
      zh: >
          确保密钥对**与** `Security.user_signature` 都在 —— 否则 XXMI 会重新生成密钥，把我们写的注入列表一并作废。
          
      en: >
          Make sure both the key pair AND Security.user_signature exist — otherwise XXMI regenerates its key and wipes our injection list.
          
  - protocol: rpc
    path: "sign_xxmi_setting"
    description:
      zh: >
          按 XXMI 的校验方式签一个 unsecure 设置值（ECDSA P-384 + SHA-256、base64 DER）。
          
      en: >
          Sign one unsecure setting value (ECDSA P-384 + SHA-256, base64 DER) exactly as XXMI verifies it.
          
---
