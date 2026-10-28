<?php

declare(strict_types=1);

namespace App\Support;

final class Validator
{
    public const LOCAL_PART_PATTERN = '/^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$/';

    public static function email(string $value): bool
    {
        if (strlen($value) > 254 || !str_contains($value, '@')) {
            return false;
        }

        [$local, $domain] = explode('@', $value, 2);

        return self::localPart($local) && self::domain($domain);
    }

    public static function localPart(string $value): bool
    {
        return strlen($value) <= 64
            && preg_match(self::LOCAL_PART_PATTERN, $value) === 1
            && !str_contains($value, '..');
    }

    public static function domain(string $value): bool
    {
        if (strlen($value) < 4 || strlen($value) > 190) {
            return false;
        }

        return preg_match('/^(?=.{4,190}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$/i', $value) === 1;
    }

    public static function hostname(string $value): bool
    {
        return self::domain($value) || filter_var($value, FILTER_VALIDATE_IP) !== false;
    }

    /** Trim + reject control characters (header injection guard). */
    public static function headerSafe(string $value): bool
    {
        return preg_match('/[\r\n\0]/', $value) !== 1;
    }

    public static function int(mixed $value, int $min, int $max): ?int
    {
        if (!is_numeric($value)) {
            return null;
        }

        $int = (int) $value;

        return $int >= $min && $int <= $max ? $int : null;
    }
}
