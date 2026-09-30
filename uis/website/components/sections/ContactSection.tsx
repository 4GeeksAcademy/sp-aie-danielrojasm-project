import { ButtonLink } from "@/components/ui/ButtonLink";

interface ContactSectionProps {
  title: string;
  description: string;
  email: string;
  applicationHref: string;
}

export function ContactSection({
  title,
  description,
  email,
  applicationHref,
}: ContactSectionProps) {
  return (
    <section
      id="contacto"
      className="mx-auto w-full max-w-7xl scroll-mt-24 px-4 py-16 sm:px-6 lg:px-8"
      aria-labelledby="contacto-title"
    >
      <div className="rounded-3xl border border-cyan-300/30 bg-cyan-400/10 p-8 sm:p-10">
        <h2
          id="contacto-title"
          className="text-3xl font-extrabold text-white sm:text-4xl"
        >
          {title}
        </h2>
        <p className="mt-4 max-w-3xl text-slate-200">{description}</p>
        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <ButtonLink href={applicationHref} variant="light">
            Ir al formulario de aplicación
          </ButtonLink>
          <ButtonLink href={`mailto:${email}`} variant="ghost-light">
            {email}
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}
