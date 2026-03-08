import { cn } from "@/lib/utils";

export function Table({ className, ...props }) {
  return <table className={cn("w-full text-sm", className)} {...props} />;
}

export function THead({ className, ...props }) {
  return <thead className={cn("bg-secondary/60", className)} {...props} />;
}

export function TBody({ className, ...props }) {
  return <tbody className={cn("divide-y", className)} {...props} />;
}

export function TH({ className, ...props }) {
  return <th className={cn("px-3 py-2 text-left font-semibold", className)} {...props} />;
}

export function TD({ className, ...props }) {
  return <td className={cn("px-3 py-2 align-top", className)} {...props} />;
}
