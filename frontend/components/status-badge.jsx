export function StatusBadge({ status }) {
  const map = {
    new: "info",
    saved: "default",
    ready: "info",
    applied: "warning",
    interview: "success",
    rejected: "danger",
  };

  const variant = map[(status || "new").toLowerCase()] || "default";

  const variantClass = {
    info: "border-blue-300 bg-blue-100 text-blue-700 dark:border-blue-800 dark:bg-blue-950/50 dark:text-blue-300",
    default: "border-border bg-secondary text-secondary-foreground",
    warning: "border-amber-300 bg-amber-100 text-amber-700 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
    success: "border-emerald-300 bg-emerald-100 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300",
    danger: "border-rose-300 bg-rose-100 text-rose-700 dark:border-rose-800 dark:bg-rose-950/50 dark:text-rose-300",
  };

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${variantClass[variant]}`}>
      {(status || "new").toLowerCase()}
    </span>
  );
}
