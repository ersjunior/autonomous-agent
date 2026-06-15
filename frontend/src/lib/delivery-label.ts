import type { BadgeVariant } from "@/components/ui/Badge";

export function deliveryBadgeVariant(label: string | null | undefined): BadgeVariant {
  if (!label) return "muted";
  if (label.startsWith("Entregue")) return "success";
  if (label.startsWith("Falhou")) return "warning";
  return "default";
}
