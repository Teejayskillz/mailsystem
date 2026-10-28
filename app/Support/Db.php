<?php

declare(strict_types=1);

namespace App\Support;

use PDO;
use PDOException;
use Throwable;

final class Db
{
    /** @param array<string, mixed> $cfg */
    public static function connect(array $cfg): PDO
    {
        $dsn = (string) ($cfg['dsn'] ?? '');
        $user = isset($cfg['user']) ? (string) $cfg['user'] : null;
        $pass = isset($cfg['pass']) ? (string) $cfg['pass'] : null;

        $options = [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_STRINGIFY_FETCHES => false,
        ];

        if (str_starts_with($dsn, 'mysql:')) {
            $options[PDO::ATTR_EMULATE_PREPARES] = false;
        }

        $pdo = new PDO($dsn, $user, $pass, $options);

        if (str_starts_with($dsn, 'mysql:')) {
            $pdo->exec("SET time_zone = '+00:00'");
        }

        return $pdo;
    }

    /**
     * True when the exception is a duplicate-key/unique-constraint error.
     * Works for both MySQL (SQLSTATE 23000) and SQLite.
     */
    public static function isUniqueViolation(Throwable $e): bool
    {
        if (!$e instanceof PDOException) {
            return false;
        }

        $sqlState = $e->errorInfo[0] ?? null;
        if ($sqlState === '23000') {
            return true;
        }

        $message = $e->getMessage();

        return str_contains($message, 'UNIQUE constraint failed')
            || str_contains($message, 'Duplicate entry')
            || str_contains($message, 'duplicate key value');
    }

    public static function isMysql(PDO $pdo): bool
    {
        return $pdo->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql';
    }
}
