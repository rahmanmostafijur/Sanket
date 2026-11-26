import { cn } from "@/lib/cn"

/** shadcn Skeleton with the Sanket shimmer (`.skeleton` in index.css). */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      aria-hidden
      data-slot="skeleton"
      className={cn("skeleton rounded-md", className)}
      {...props}
    />
  )
}

export { Skeleton }
