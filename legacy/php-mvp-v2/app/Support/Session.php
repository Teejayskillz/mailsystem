<?php

declare(strict_types=1);

namespace App\Support;

/**
 * Hardened PHP session handling.
 *
 * Cookie flags, strict mode, id regeneration, idle/absolute timeouts and a
 * per-user "session epoch" so every session can be revoked from the database.
 */
final class Session
{
    private const KEY_ADMIN = 'admin_id';
    private const KEY_EPOCH = 'epoch';
    private const KEY_CREATED = 'created_at';
    private const KEY_SEEN = 'seen_at';
    private const KEY_UA = 'ua_hash';
    private const KEY_CSRF = 'csrf_token';

    /** @var array<string, mixed> */
    private static array $config = [];

    public static function start(array $config, string $savePath): void
    {
        self::$config = $config;

        if (session_status() === PHP_SESSION_ACTIVE) {
            return;
        }

        if (!is_dir($savePath)) {
            @mkdir($savePath, 0700, true);
        }

        ini_set('session.save_path', $savePath);
        ini_set('session.use_strict_mode', '1');
        ini_set('session.use_only_cookies', '1');
        ini_set('session.use_trans_sid', '0');
        ini_set('session.cookie_httponly', '1');
        ini_set('session.sid_length', '48');
        ini_set('session.sid_bits_per_character', '6');
        ini_set('session.gc_maxlifetime', (string) max(3600, (int) ($config['absolute_seconds'] ?? 43200)));
        ini_set('session.cookie_samesite', 'Strict');

        session_name((string) ($config['name'] ?? 'mailgen_session'));

        $https = (($_SERVER['HTTPS'] ?? '') !== '' && ($_SERVER['HTTPS'] ?? '') !== 'off')
            || (($_SERVER['SERVER_PORT'] ?? '') === '443')
            || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');

        session_set_cookie_params([
            'lifetime' => 0,
            'path' => '/',
            'domain' => '',
            'secure' => $https,
            'httponly' => true,
            'samesite' => 'Strict',
        ]);

        session_start();
    }

    public static function get(string $key, mixed $default = null): mixed
    {
        return $_SESSION[$key] ?? $default;
    }

    public static function set(string $key, mixed $value): void
    {
        $_SESSION[$key] = $value;
    }

    public static function forget(string $key): void
    {
        unset($_SESSION[$key]);
    }

    public static function regenerate(): void
    {
        if (session_status() === PHP_SESSION_ACTIVE) {
            session_regenerate_id(true);
        }
    }

    public static function destroy(): void
    {
        if (session_status() !== PHP_SESSION_ACTIVE) {
            return;
        }

        $_SESSION = [];

        if (ini_get('session.use_cookies')) {
            $params = session_get_cookie_params();
            setcookie(session_name(), '', [
                'expires' => time() - 42000,
                'path' => $params['path'],
                'domain' => $params['domain'],
                'secure' => (bool) $params['secure'],
                'httponly' => (bool) $params['httponly'],
                'samesite' => $params['samesite'] ?? 'Strict',
            ]);
        }

        session_destroy();
    }

    public static function login(int $adminId, int $epoch): void
    {
        self::regenerate();
        $_SESSION = [
            self::KEY_ADMIN => $adminId,
            self::KEY_EPOCH => $epoch,
            self::KEY_CREATED => time(),
            self::KEY_SEEN => time(),
            self::KEY_UA => self::userAgentHash(),
        ];
    }

    public static function logout(): void
    {
        self::destroy();
    }

    public static function adminId(): ?int
    {
        $id = $_SESSION[self::KEY_ADMIN] ?? null;

        return is_numeric($id) ? (int) $id : null;
    }

    public static function epoch(): ?int
    {
        $epoch = $_SESSION[self::KEY_EPOCH] ?? null;

        return is_numeric($epoch) ? (int) $epoch : null;
    }

    /**
     * Enforce idle/absolute timeout and user-agent binding.
     * Returns false when the session must be considered invalid.
     */
    public static function touch(): bool
    {
        if (self::adminId() === null) {
            return false;
        }

        $now = time();
        $seen = (int) ($_SESSION[self::KEY_SEEN] ?? 0);
        $created = (int) ($_SESSION[self::KEY_CREATED] ?? 0);

        $idle = (int) (self::$config['idle_seconds'] ?? 1800);
        $absolute = (int) (self::$config['absolute_seconds'] ?? 43200);

        if ($seen > 0 && ($now - $seen) > $idle) {
            self::logout();

            return false;
        }

        if ($created > 0 && ($now - $created) > $absolute) {
            self::logout();

            return false;
        }

        $boundUa = (string) ($_SESSION[self::KEY_UA] ?? '');
        if ($boundUa !== '' && !hash_equals($boundUa, self::userAgentHash())) {
            self::logout();

            return false;
        }

        $_SESSION[self::KEY_SEEN] = $now;

        return true;
    }

    public static function csrfToken(): string
    {
        $token = $_SESSION[self::KEY_CSRF] ?? null;

        if (!is_string($token) || strlen($token) < 32) {
            $token = bin2hex(random_bytes(32));
            $_SESSION[self::KEY_CSRF] = $token;
        }

        return $token;
    }

    public static function rotateCsrf(): void
    {
        $_SESSION[self::KEY_CSRF] = bin2hex(random_bytes(32));
    }

    public static function userAgentHash(): string
    {
        return hash('sha256', $_SERVER['HTTP_USER_AGENT'] ?? 'unknown');
    }

    /** @param array<string, string> $flash */
    public static function flash(string $type, string $message): void
    {
        $_SESSION['_flash'][] = ['type' => $type, 'message' => $message];
    }

    /** @return list<array<string, string>> */
    public static function takeFlashes(): array
    {
        $flashes = $_SESSION['_flash'] ?? [];
        unset($_SESSION['_flash']);

        return is_array($flashes) ? $flashes : [];
    }
}
