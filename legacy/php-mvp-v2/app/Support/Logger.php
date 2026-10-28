<?php

declare(strict_types=1);

namespace App\Support;

/**
 * Minimal PSR-3-ish file logger. Never writes secrets to disk.
 */
final class Logger
{
    public function __construct(
        private readonly string $directory,
        private readonly bool $debug = false,
    ) {
        if (!is_dir($this->directory)) {
            @mkdir($this->directory, 0700, true);
        }
    }

    /** @param array<string, mixed> $context */
    public function info(string $event, array $context = []): void
    {
        $this->write('info', $event, $context);
    }

    /** @param array<string, mixed> $context */
    public function warning(string $event, array $context = []): void
    {
        $this->write('warning', $event, $context);
    }

    /** @param array<string, mixed> $context */
    public function error(string $event, array $context = []): void
    {
        $this->write('error', $event, $context);
    }

    /** @param array<string, mixed> $context */
    private function write(string $level, string $event, array $context): void
    {
        $line = json_encode([
            'ts' => Clock::now(),
            'level' => $level,
            'event' => $event,
            'ctx' => $this->redact($context),
            'pid' => getmypid(),
        ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PARTIAL_OUTPUT_ON_ERROR);

        if ($line === false) {
            return;
        }

        $file = rtrim($this->directory, '/\\') . DIRECTORY_SEPARATOR . 'app-' . gmdate('Y-m-d') . '.log';
        @file_put_contents($file, $line . PHP_EOL, FILE_APPEND | LOCK_EX);
    }

    /**
     * @param array<string, mixed> $context
     * @return array<string, mixed>
     */
    private function redact(array $context): array
    {
        $secretKeys = '/pass(word)?|token|secret|app_key|api_key|authorization|credential/i';

        array_walk_recursive($context, static function (&$value, $key) use ($secretKeys): void {
            if (is_string($key) && preg_match($secretKeys, $key) === 1) {
                $value = '[redacted]';
            }
        });

        return $context;
    }

    public function debugEnabled(): bool
    {
        return $this->debug;
    }
}
