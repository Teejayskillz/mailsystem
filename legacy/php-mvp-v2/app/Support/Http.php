<?php

declare(strict_types=1);

namespace App\Support;

final class Http
{
    public static function method(): string
    {
        return strtoupper($_SERVER['REQUEST_METHOD'] ?? 'GET');
    }

    public static function isPost(): bool
    {
        return self::method() === 'POST';
    }

    public static function path(): string
    {
        $uri = $_SERVER['REQUEST_URI'] ?? '/';
        $path = parse_url($uri, PHP_URL_PATH);

        if (!is_string($path) || $path === '') {
            return '/';
        }

        $path = '/' . ltrim($path, '/');

        return $path === '/' ? '/' : rtrim($path, '/');
    }

    public static function query(string $key, mixed $default = null): mixed
    {
        return $_GET[$key] ?? $default;
    }

    public static function post(string $key, mixed $default = null): mixed
    {
        return $_POST[$key] ?? $default;
    }

    public static function input(string $key, mixed $default = null): mixed
    {
        return self::isPost() ? self::post($key, $default) : self::query($key, $default);
    }

    public static function ip(): string
    {
        $ip = $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';

        return is_string($ip) && filter_var($ip, FILTER_VALIDATE_IP) ? $ip : '0.0.0.0';
    }

    public static function userAgent(): string
    {
        $ua = $_SERVER['HTTP_USER_AGENT'] ?? '';

        return is_string($ua) ? substr($ua, 0, 400) : '';
    }

    public static function isSecure(): bool
    {
        return (($_SERVER['HTTPS'] ?? '') !== '' && ($_SERVER['HTTPS'] ?? '') !== 'off')
            || (($_SERVER['SERVER_PORT'] ?? '') === '443')
            || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
    }

    public static function wantsJson(): bool
    {
        $accept = $_SERVER['HTTP_ACCEPT'] ?? '';
        $requestedWith = $_SERVER['HTTP_X_REQUESTED_WITH'] ?? '';

        return str_contains((string) $accept, 'application/json')
            || strtolower((string) $requestedWith) === 'xmlhttprequest';
    }

    public static function header(string $name, string $value, bool $replace = true): void
    {
        if (!headers_sent()) {
            header($name . ': ' . $value, $replace);
        }
    }

    public static function redirect(string $location, int $status = 303): never
    {
        if (!headers_sent()) {
            header('Location: ' . $location, true, $status);
        }
        exit;
    }

    /** @param array<string, mixed> $payload */
    public static function json(array $payload, int $status = 200): never
    {
        if (!headers_sent()) {
            http_response_code($status);
            header('Content-Type: application/json; charset=utf-8');
            header('Cache-Control: no-store');
        }
        echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        exit;
    }

    /**
     * Same-origin check for state-changing requests: rejects cross-site form posts
     * even if a CSRF token were ever leaked.
     */
    public static function isSameOriginRequest(): bool
    {
        $site = strtolower((string) ($_SERVER['HTTP_SEC_FETCH_SITE'] ?? ''));
        if ($site !== '' && !in_array($site, ['same-origin', 'same-site', 'none'], true)) {
            return false;
        }

        $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
        if ($origin === '') {
            return true;
        }

        $host = $_SERVER['HTTP_HOST'] ?? '';
        if ($host === '') {
            return false;
        }

        $originHost = parse_url((string) $origin, PHP_URL_HOST);
        $originPort = parse_url((string) $origin, PHP_URL_PORT);
        $originAuthority = $originHost === null ? null : $originHost . ($originPort !== null ? ':' . $originPort : '');

        return is_string($originAuthority) && hash_equals(strtolower((string) $host), strtolower($originAuthority));
    }
}
