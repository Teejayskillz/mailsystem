<?php

declare(strict_types=1);

namespace App\Support;

/**
 * Per-session CSRF token.
 *
 * The same token is used for the lifetime of a session (multi-tab friendly) and
 * is rotated on login. Validation is constant-time and also checks that the
 * request itself is same-origin.
 */
final class Csrf
{
    public const FIELD = '_csrf';

    public static function token(): string
    {
        return Session::csrfToken();
    }

    public static function field(): string
    {
        return '<input type="hidden" name="' . self::FIELD . '" value="'
            . htmlspecialchars(self::token(), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . '">';
    }

    public static function check(?string $submitted): bool
    {
        if (!is_string($submitted) || $submitted === '') {
            return false;
        }

        $expected = Session::csrfToken();

        return hash_equals($expected, $submitted) && Http::isSameOriginRequest();
    }

    /**
     * Validate the token from either the form body or the X-CSRF-Token header.
     */
    public static function checkRequest(): bool
    {
        $token = Http::post(self::FIELD);

        if (!is_string($token) || $token === '') {
            $token = $_SERVER['HTTP_X_CSRF_TOKEN'] ?? null;
        }

        return self::check(is_string($token) ? $token : null);
    }

    public static function rotate(): void
    {
        Session::rotateCsrf();
    }
}
