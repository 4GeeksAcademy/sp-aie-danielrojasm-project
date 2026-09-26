interface SectionHeadingProps {
  id: string;
  title: string;
  description?: string;
}

export function SectionHeading({ id, title, description }: SectionHeadingProps) {
  return (
    <div className="mb-10 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <h2 id={id} className="text-3xl font-extrabold text-white sm:text-4xl">
        {title}
      </h2>
      {description ? (
        <p className="max-w-xl text-slate-300">{description}</p>
      ) : null}
    </div>
  );
}
