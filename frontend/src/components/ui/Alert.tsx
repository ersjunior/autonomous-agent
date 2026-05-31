import type { ReactNode } from "react";

type AlertVariant = "error" | "warning" | "info";

const styles: Record<AlertVariant, string> = {
  error: "border-destructive/30 bg-destructive/10 text-destructive",
  warning: "border-warning/30 bg-warning/10 text-amber-700 dark:text-amber-300",
  info: "border-primary/30 bg-primary/10 text-primary",
};

export function Alert({
  children,
  variant = "error",
}: {
  children: ReactNode;
  variant?: AlertVariant;
}) {
  return (
    <div className={`mb-4 rounded-xl border px-4 py-3 text-sm ${styles[variant]}`}>
      {children}
    </div>
  );
}
