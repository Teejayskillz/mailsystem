<?php

declare(strict_types=1);

namespace App\Support;

use SodiumException;

/**
 * Password/hash helpers: app key handling, authenticated encryption for the
 * mailbox passwords stored in the database, and HMAC-signed tokens.
 */
final class Crypto
{
    private const CIPHER = 'sodium_crypto_secretbox';

    private function __construct(private readonly string $key)
    {
        if (strlen($this->key) !== SODIUM_CRYPTO_SECRETBOX_KEYBYTES) {
            throw new CryptoException('App key must be exactly 32 bytes.');
        }
    }

    public static function fromBase64(string $encoded): self
    {
        $raw = base64_decode(trim($encoded), true);

        if ($raw === false) {
            throw new CryptoException('App key is not valid base64.');
        }

        return new self($raw);
    }

    public static function generateKeyBase64(): string
    {
        return base64_encode(random_bytes(SODIUM_CRYPTO_SECRETBOX_KEYBYTES));
    }

    /** @param array<string, mixed> $cfg */
    public static function fromConfig(Config $config): self
    {
        return self::fromBase64($config->string('security.app_key'));
    }

    /** Returns base64(nonce . ciphertext). */
    public function seal(string $plaintext): string
    {
        $nonce = random_bytes(SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
        $ciphertext = sodium_crypto_secretbox($plaintext, $nonce, $this->key);

        return base64_encode($nonce . $ciphertext);
    }

    public function open(string $sealed): string
    {
        $raw = base64_decode($sealed, true);

        if ($raw === false || strlen($raw) <= SODIUM_CRYPTO_SECRETBOX_NONCEBYTES) {
            throw new CryptoException('Stored secret is malformed.');
        }

        $nonce = substr($raw, 0, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
        $ciphertext = substr($raw, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);

        try {
            $plain = sodium_crypto_secretbox_open($ciphertext, $nonce, $this->key);
        } catch (SodiumException $e) {
            throw new CryptoException('Stored secret could not be decrypted.', 0, $e);
        }

        if ($plain === false) {
            throw new CryptoException('Stored secret could not be decrypted (wrong app key?).');
        }

        return $plain;
    }

    /** URL-safe random token. */
    public function randomToken(int $bytes = 32): string
    {
        return rtrim(strtr(base64_encode(random_bytes($bytes)), '+/', '-_'), '=');
    }

    public function hmac(string $data): string
    {
        return hash_hmac('sha256', $data, $this->key);
    }

    public function hashEquals(string $known, string $userSupplied): bool
    {
        return hash_equals($known, $userSupplied);
    }

    /** Non-reversible fingerprint, for logging/rate-limit keys. */
    public function fingerprint(string $value): string
    {
        return substr(hash_hmac('sha256', $value, $this->key), 0, 16);
    }
}
