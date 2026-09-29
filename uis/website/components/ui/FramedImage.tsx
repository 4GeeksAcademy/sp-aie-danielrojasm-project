import Image from "next/image";
import type { ImageAsset } from "@/types/site";

interface FramedImageProps {
  image: ImageAsset;
  priority?: boolean;
}

export function FramedImage({ image, priority = false }: FramedImageProps) {
  return (
    <div className="relative h-80 w-full overflow-hidden rounded-2xl shadow-2xl ring-1 ring-cyan-200/20 sm:h-96">
      <Image
        src={image.src}
        alt={image.alt}
        fill
        priority={priority}
        sizes="(min-width: 1024px) 50vw, 100vw"
        className="object-cover"
      />
    </div>
  );
}
