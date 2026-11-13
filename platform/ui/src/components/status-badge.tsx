import { IconAlertTriangle, IconCircleCheck, IconLoader2, IconTrash } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import type { ProjectStatus } from "@/lib/platform";

const LABELS: Record<ProjectStatus, string> = {
  provisioning: "Provisioning",
  running: "Running",
  failed: "Failed",
  deleting: "Deleting",
  deleted: "Deleted",
};

export function StatusBadge({ status }: { status: ProjectStatus }) {
  if (status === "running") {
    return (
      <Badge variant="outline" className="text-emerald-700 dark:text-emerald-400">
        <IconCircleCheck /> {LABELS[status]}
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="destructive">
        <IconAlertTriangle /> {LABELS[status]}
      </Badge>
    );
  }
  if (status === "deleting" || status === "deleted") {
    return (
      <Badge variant="secondary">
        <IconTrash /> {LABELS[status]}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary">
      <IconLoader2 className="animate-spin" /> {LABELS[status]}
    </Badge>
  );
}
