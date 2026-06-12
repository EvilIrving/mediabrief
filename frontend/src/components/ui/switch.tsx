import * as React from "react"
import * as SwitchPrimitives from "@radix-ui/react-switch"
import { cn } from "@/lib/utils"

const Switch = React.forwardRef<
  React.ComponentRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      "peer inline-flex h-[22px] w-[40px] shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-300",
      "bg-[var(--surface-3)]",
      "data-[state=checked]:bg-[var(--accent)]",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-dim)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)]",
      "disabled:cursor-not-allowed disabled:opacity-50",
      className
    )}
    {...props}
    ref={ref}
  >
    <SwitchPrimitives.Thumb
      className={cn(
        "pointer-events-none block h-4 w-4 rounded-full shadow-lg ring-0 transition-transform duration-300",
        "bg-[var(--text-muted)]",
        "data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-[var(--text-on-accent)]",
        "data-[state=unchecked]:translate-x-0"
      )}
    />
  </SwitchPrimitives.Root>
))
Switch.displayName = SwitchPrimitives.Root.displayName

export { Switch }
