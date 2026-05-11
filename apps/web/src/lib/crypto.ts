import { createCipheriv, randomBytes } from "crypto";

/** AES-256-GCM; matches `apps/pipeline/app/secrets.py` (nonce || ciphertext+tag, base64). */
export function encryptSecret(masterKeyB64: string, plaintext: string): string {
  const key = Buffer.from(masterKeyB64, "base64");
  if (key.length !== 32) {
    throw new Error("MASTER_ENCRYPTION_KEY must decode to exactly 32 bytes");
  }
  const nonce = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, nonce);
  const enc = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([nonce, enc, tag]).toString("base64");
}
