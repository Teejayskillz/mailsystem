<?php

declare(strict_types=1);

namespace App\Support;

final class View
{
    /** @param array<string, mixed> $globals */
    public function __construct(
        private readonly string $directory,
        private readonly array $globals = [],
    ) {
    }

    /** @param array<string, mixed> $data */
    public function render(string $template, array $data = [], ?string $layout = 'layout'): string
    {
        $content = $this->renderFile($template, $data);

        if ($layout === null) {
            return $content;
        }

        return $this->renderFile($layout, array_merge($data, ['content' => $content]));
    }

    /** @param array<string, mixed> $data */
    private function renderFile(string $template, array $data): string
    {
        $file = rtrim($this->directory, '/\\') . DIRECTORY_SEPARATOR . $template . '.php';

        if (!is_file($file)) {
            throw new \RuntimeException('View not found: ' . $template);
        }

        $scope = array_merge($this->globals, $data);
        $scope['e'] = static fn (mixed $value): string => self::escape($value);

        extract($scope, EXTR_SKIP);
        ob_start();

        try {
            require $file;

            return (string) ob_get_clean();
        } catch (\Throwable $e) {
            ob_end_clean();
            throw $e;
        }
    }

    public static function escape(mixed $value): string
    {
        if ($value === null) {
            return '';
        }

        if (is_bool($value)) {
            return $value ? '1' : '';
        }

        if (!is_scalar($value) && !($value instanceof \Stringable)) {
            return '';
        }

        return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }
}
