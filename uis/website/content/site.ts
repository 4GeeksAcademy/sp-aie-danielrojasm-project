import type {
  CompanyInfo,
  FeatureItem,
  HeroContent,
  ImageAsset,
  NavLink,
} from "@/types/site";

export const APPLICATION_PATH = "/aplicar";

export const company: CompanyInfo = {
  name: "TrackFlow",
  tagline: "Logística 24/7",
  description:
    "Empresa de logística de última milla y gestión de almacenes con operaciones en Estados Unidos y España.",
  url: "https://trackflow.example",
  email: "hola@trackflow.example",
  phone: "+1-213-555-0147",
  phoneDisplay: "+1 213 555 0147",
  foundingYear: 2009,
  employees: 130,
  offices: [
    {
      city: "Los Ángeles",
      region: "California",
      country: "EE. UU.",
      streetAddress: "Downtown Logistics District",
      postalCode: "90012",
      countryCode: "US",
    },
    {
      city: "Zaragoza",
      region: "Aragón",
      country: "España",
      streetAddress: "Plataforma Logística de Zaragoza",
      postalCode: "50014",
      countryCode: "ES",
    },
  ],
  socialProfiles: [
    "https://www.linkedin.com/company/trackflow",
    "https://x.com/trackflow",
  ],
};

export const navLinks: NavLink[] = [
  { label: "Servicios", href: "/#servicios" },
  { label: "Beneficios", href: "/#beneficios" },
  { label: "Contacto", href: "/#contacto" },
];

export const hero: HeroContent = {
  eyebrow: "Operaciones en USA y España",
  title: "Logística moderna para marcas que no pueden permitirse fricciones",
  description:
    "Unificamos inventario, envíos, devoluciones y atención al cliente en una sola operación conectada. Menos retrasos, menos errores y decisiones en tiempo real.",
  image: {
    src: "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?auto=format&fit=crop&w=1200&q=80",
    alt: "Operaria revisando paquetes en un almacén de comercio electrónico",
  },
  highlight: { label: "Rendimiento actual", value: "98.1% entregas a tiempo" },
};

export const servicesIntro =
  "Desde que entra un pedido hasta que se entrega o se devuelve, TrackFlow coordina toda la cadena logística.";

export const services: FeatureItem[] = [
  {
    title: "Inventario unificado",
    description:
      "Visibilidad de stock en tiempo real entre Los Ángeles y Zaragoza para reducir roturas y sobreventas.",
  },
  {
    title: "Selección inteligente de transportista",
    description:
      "Elegimos la mejor opción por destino, urgencia y coste para mejorar puntualidad y margen.",
  },
  {
    title: "Devoluciones automatizadas",
    description:
      "Reglas configurables por cliente para aprobar, etiquetar y procesar devoluciones sin cuellos de botella.",
  },
];

export const benefits: FeatureItem[] = [
  {
    title: "Operación continua",
    description:
      "Soporte y seguimiento disponibles 24/7 para reducir incertidumbre en cada pedido.",
  },
  {
    title: "Escala internacional",
    description:
      "Una sola capa operativa para dos países, dos almacenes y múltiples transportistas.",
  },
  {
    title: "Decisión con datos",
    description:
      "Dashboards en tiempo real para tomar decisiones antes de que aparezcan incidencias.",
  },
];

export const benefitsImage: ImageAsset = {
  src: "https://images.unsplash.com/photo-1587293852726-70cdb56c2866?auto=format&fit=crop&w=1200&q=80",
  alt: "Mapa logístico con rutas y seguimiento de entregas en pantalla",
};

export const contactCta = {
  title: "Listo para modernizar tu logística",
  description:
    "Cuéntanos tu operación y te propondremos un plan de implementación alineado a tus objetivos de coste, velocidad y experiencia de cliente.",
};
