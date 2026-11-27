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
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.088Z"
fingerprint: a37b902f3c1838d9ab6da9f527cba86f1d48ecf61c1eb2068da6d3843143db4c
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 1298
    end_line: 4429
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
