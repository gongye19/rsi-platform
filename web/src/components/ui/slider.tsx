"use client";

import * as React from "react";
import { Slider as SliderPrimitive } from "radix-ui";
import { cn } from "cn";

function Slider({ className, ...props }: React.ComponentProps<typeof SliderPrimitive.Root>) {
  return <SliderPrimitive.Root className={cn("ce-slider", className)} {...props}>
    <SliderPrimitive.Track className="ce-slider-track"><SliderPrimitive.Range className="ce-slider-range" /></SliderPrimitive.Track>
    <SliderPrimitive.Thumb className="ce-slider-thumb" aria-label={props["aria-label"]} />
  </SliderPrimitive.Root>;
}
export { Slider };
