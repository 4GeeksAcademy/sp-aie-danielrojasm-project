/**
 * Reglas del formulario de aplicación B2B (portadas del antiguo uis/website/validation.js del Hito 1
 * a funciones puras y tipadas, testeables sin DOM).
 */

export type OperatingCountry = "US" | "ES" | "BOTH";
export type ProjectPriority = "alta" | "media" | "baja";
export type ServiceInterest =
  | "inventario"
  | "tracking"
  | "returns"
  | "cx"
  | "executive";

export interface ApplicationFormValues {
  fullName: string;
  jobTitle: string;
  email: string;
  phone: string;
  companyName: string;
  country: OperatingCountry | "";
  warehouseCount: string;
  website: string;
  monthlyShipments: string;
  returnsRate: string;
  goLiveDate: string;
  priority: ProjectPriority | "";
  services: ServiceInterest[];
  mainPain: string;
  privacyAccepted: boolean;
}

export type ApplicationField = keyof ApplicationFormValues;
export type ApplicationErrors = Partial<Record<ApplicationField, string>>;

export interface SelectOption<T extends string> {
  value: T;
  label: string;
}

export const countryOptions: SelectOption<OperatingCountry>[] = [
  { value: "US", label: "Estados Unidos" },
  { value: "ES", label: "España" },
  { value: "BOTH", label: "Ambos mercados" },
];

export const priorityOptions: SelectOption<ProjectPriority>[] = [
  { value: "alta", label: "Alta (0-3 meses)" },
  { value: "media", label: "Media (3-6 meses)" },
  { value: "baja", label: "Baja (+6 meses)" },
];

export const serviceOptions: SelectOption<ServiceInterest>[] = [
  { value: "inventario", label: "Inventario unificado en tiempo real" },
  { value: "tracking", label: "Tracking unificado de transportistas" },
  { value: "returns", label: "Automatización de devoluciones" },
  { value: "cx", label: "Agente de CX y tickets" },
  { value: "executive", label: "Dashboard ejecutivo y reportes automáticos" },
];

export const emptyApplication: ApplicationFormValues = {
  fullName: "",
  jobTitle: "",
  email: "",
  phone: "",
  companyName: "",
  country: "",
  warehouseCount: "",
  website: "",
  monthlyShipments: "",
  returnsRate: "",
  goLiveDate: "",
  priority: "",
  services: [],
  mainPain: "",
  privacyAccepted: false,
};

const REQUIRED_MESSAGE = "Este campo es obligatorio.";

function isInRange(value: string, min: number, max: number): boolean {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= min && parsed <= max;
}

function isTodayOrFuture(value: string, today: Date): boolean {
  if (!value) return false;
  const selected = new Date(`${value}T00:00:00`);
  const startOfToday = new Date(today);
  startOfToday.setHours(0, 0, 0, 0);
  return !Number.isNaN(selected.getTime()) && selected >= startOfToday;
}

type FieldValidator = (
  values: ApplicationFormValues,
  today: Date,
) => string | null;

const validators: Record<ApplicationField, FieldValidator> = {
  fullName: ({ fullName }) => {
    if (!fullName.trim()) return REQUIRED_MESSAGE;
    return /^[A-Za-zÀ-ÿ\s'-]{3,}$/.test(fullName.trim())
      ? null
      : "Ingresa un nombre válido (mínimo 3 caracteres, solo letras y espacios).";
  },
  jobTitle: ({ jobTitle }) => {
    if (!jobTitle.trim()) return REQUIRED_MESSAGE;
    return jobTitle.trim().length >= 2
      ? null
      : "Ingresa tu cargo (mínimo 2 caracteres).";
  },
  email: ({ email }) => {
    if (!email.trim()) return REQUIRED_MESSAGE;
    return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim())
      ? null
      : "Ingresa un email corporativo válido.";
  },
  phone: ({ phone }) => {
    if (!phone.trim()) return REQUIRED_MESSAGE;
    return /^\+?[0-9\s()-]{7,20}$/.test(phone.trim())
      ? null
      : "Ingresa un teléfono válido (7 a 20 dígitos, puede incluir +, espacios o guiones).";
  },
  companyName: ({ companyName }) => {
    if (!companyName.trim()) return REQUIRED_MESSAGE;
    return companyName.trim().length >= 2
      ? null
      : "Ingresa el nombre de tu empresa.";
  },
  country: ({ country }) =>
    country ? null : "Selecciona el país principal de operación.",
  warehouseCount: ({ warehouseCount }) => {
    if (!warehouseCount.trim()) return REQUIRED_MESSAGE;
    const parsed = Number(warehouseCount);
    return Number.isInteger(parsed) && parsed >= 1 && parsed <= 50
      ? null
      : "El número de almacenes debe estar entre 1 y 50.";
  },
  website: ({ website }) => {
    if (!website.trim()) return null;
    return /^https?:\/\/.+\..+/.test(website.trim())
      ? null
      : "El sitio web debe comenzar con http:// o https:// y ser una URL válida.";
  },
  monthlyShipments: ({ monthlyShipments }) => {
    if (!monthlyShipments.trim()) return REQUIRED_MESSAGE;
    return isInRange(monthlyShipments, 100, 2_000_000)
      ? null
      : "El volumen mensual debe estar entre 100 y 2,000,000 envíos.";
  },
  returnsRate: ({ returnsRate }) => {
    if (!returnsRate.trim()) return REQUIRED_MESSAGE;
    return isInRange(returnsRate, 0, 100)
      ? null
      : "La tasa de devoluciones debe estar entre 0 y 100%.";
  },
  goLiveDate: ({ goLiveDate }, today) => {
    if (!goLiveDate) return REQUIRED_MESSAGE;
    return isTodayOrFuture(goLiveDate, today)
      ? null
      : "Selecciona una fecha de implementación válida (hoy o futura).";
  },
  priority: ({ priority }) =>
    priority ? null : "Selecciona la prioridad del proyecto.",
  services: ({ services }) =>
    services.length > 0 ? null : "Selecciona al menos un servicio de interés.",
  mainPain: ({ mainPain }) => {
    if (!mainPain.trim()) return REQUIRED_MESSAGE;
    return mainPain.trim().length >= 20
      ? null
      : "Describe el problema principal con al menos 20 caracteres.";
  },
  privacyAccepted: ({ privacyAccepted }) =>
    privacyAccepted
      ? null
      : "Debes aceptar el tratamiento de datos para continuar.",
};

export function validateApplicationField(
  field: ApplicationField,
  values: ApplicationFormValues,
  today: Date = new Date(),
): string | null {
  return validators[field](values, today);
}

export function validateApplication(
  values: ApplicationFormValues,
  today: Date = new Date(),
): ApplicationErrors {
  const errors: ApplicationErrors = {};
  for (const field of Object.keys(validators) as ApplicationField[]) {
    const message = validators[field](values, today);
    if (message) errors[field] = message;
  }
  return errors;
}
