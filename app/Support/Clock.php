<?php

declare(strict_types=1);

namespace App\Support;

final class Clock
{
    public static function now(): string
    {
        return gmdate('Y-m-d H:i:s');
    }

    public static function fromTimestamp(int $timestamp): string
    {
        return gmdate('Y-m-d H:i:s', $timestamp);
    }

    public static function timestamp(string $datetime): int
    {
        $ts = strtotime($datetime . ' UTC');

        return $ts === false ? 0 : $ts;
    }

    public static function addSeconds(int $seconds): string
    {
        return self::fromTimestamp(time() + $seconds);
    }
}
