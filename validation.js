const form = document.getElementById("applicationForm");
const successMessage = document.getElementById("successMessage");
const clearButton = document.getElementById("clearButton");

const fieldRules = {
	fullName: {
		required: true,
		validate: (value) => /^[A-Za-zÀ-ÿ\s'-]{3,}$/.test(value.trim()),
		message: "Ingresa un nombre valido (minimo 3 caracteres, solo letras y espacios)."
	},
	jobTitle: {
		required: true,
		validate: (value) => value.trim().length >= 2,
		message: "Ingresa tu cargo (minimo 2 caracteres)."
	},
	email: {
		required: true,
		validate: (value) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value.trim()),
		message: "Ingresa un email corporativo valido."
	},
	phone: {
		required: true,
		validate: (value) => /^\+?[0-9\s()-]{7,20}$/.test(value.trim()),
		message: "Ingresa un telefono valido (7 a 20 digitos, puede incluir +, espacios o guiones)."
	},
	companyName: {
		required: true,
		validate: (value) => value.trim().length >= 2,
		message: "Ingresa el nombre de tu empresa."
	},
	country: {
		required: true,
		validate: (value) => ["US", "ES", "BOTH"].includes(value),
		message: "Selecciona el pais principal de operacion."
	},
	warehouseCount: {
		required: true,
		validate: (value) => {
			const number = Number(value);
			return Number.isInteger(number) && number >= 1 && number <= 50;
		},
		message: "El numero de almacenes debe estar entre 1 y 50."
	},
	website: {
		required: false,
		validate: (value) => value.trim() === "" || /^https?:\/\/.+\..+/.test(value.trim()),
		message: "El sitio web debe comenzar con http:// o https:// y ser una URL valida."
	},
	monthlyShipments: {
		required: true,
		validate: (value) => {
			const number = Number(value);
			return Number.isFinite(number) && number >= 100 && number <= 2000000;
		},
		message: "El volumen mensual debe estar entre 100 y 2,000,000 envios."
	},
	returnsRate: {
		required: true,
		validate: (value) => {
			const number = Number(value);
			return Number.isFinite(number) && number >= 0 && number <= 100;
		},
		message: "La tasa de devoluciones debe estar entre 0 y 100%."
	},
	goLiveDate: {
		required: true,
		validate: (value) => {
			if (!value) return false;
			const selectedDate = new Date(`${value}T00:00:00`);
			const today = new Date();
			today.setHours(0, 0, 0, 0);
			return selectedDate >= today;
		},
		message: "Selecciona una fecha de implementacion valida (hoy o futura)."
	},
	priority: {
		required: true,
		validate: (value) => ["alta", "media", "baja"].includes(value),
		message: "Selecciona la prioridad del proyecto."
	},
	mainPain: {
		required: true,
		validate: (value) => value.trim().length >= 20,
		message: "Describe el problema principal con al menos 20 caracteres."
	},
	privacyAccepted: {
		required: true,
		validate: (value, field) => field.checked,
		message: "Debes aceptar el tratamiento de datos para continuar."
	}
};

const fields = Object.keys(fieldRules);

function setFieldError(field, message) {
	const errorEl = document.getElementById(`${field.id}Error`);
	if (!errorEl) return;

	field.classList.remove("border-slate-600", "focus:border-cyan-300", "focus:ring-cyan-300/30");
	field.classList.add("border-rose-400", "focus:border-rose-400", "focus:ring-rose-400/20");
	field.setAttribute("aria-invalid", "true");

	errorEl.textContent = message;
	errorEl.classList.remove("hidden");
}

function clearFieldError(field) {
	const errorEl = document.getElementById(`${field.id}Error`);
	if (!errorEl) return;

	field.classList.remove("border-rose-400", "focus:border-rose-400", "focus:ring-rose-400/20");
	field.classList.add("border-slate-600", "focus:border-cyan-300", "focus:ring-cyan-300/30");
	field.removeAttribute("aria-invalid");

	errorEl.textContent = "";
	errorEl.classList.add("hidden");
}

function validateField(fieldName) {
	const field = form.elements[fieldName];
	const rule = fieldRules[fieldName];
	if (!field || !rule) return true;

	const value = field.type === "checkbox" ? field.checked : field.value;
	const isEmpty = typeof value === "string" ? value.trim() === "" : !value;

	if (rule.required && isEmpty) {
		setFieldError(field, "Este campo es obligatorio.");
		return false;
	}

	if (!rule.required && isEmpty) {
		clearFieldError(field);
		return true;
	}

	if (!rule.validate(value, field)) {
		setFieldError(field, rule.message);
		return false;
	}

	clearFieldError(field);
	return true;
}

function setServicesError(message) {
	const errorEl = document.getElementById("servicesError");
	if (!errorEl) return;
	errorEl.textContent = message;
	errorEl.classList.remove("hidden");
}

function clearServicesError() {
	const errorEl = document.getElementById("servicesError");
	if (!errorEl) return;
	errorEl.textContent = "";
	errorEl.classList.add("hidden");
}

function validateServices() {
	const selected = [...form.querySelectorAll('input[name="services"]:checked')];
	if (selected.length === 0) {
		setServicesError("Selecciona al menos un servicio de interes.");
		return false;
	}
	clearServicesError();
	return true;
}

function validateForm() {
	const fieldsValid = fields.map(validateField).every(Boolean);
	const servicesValid = validateServices();
	return fieldsValid && servicesValid;
}

function hideSuccess() {
	successMessage.classList.add("hidden");
	successMessage.textContent = "";
}

if (form) {
	fields.forEach((fieldName) => {
		const field = form.elements[fieldName];
		if (!field) return;

		field.addEventListener("blur", () => validateField(fieldName));
		field.addEventListener("input", () => {
			validateField(fieldName);
			hideSuccess();
		});
		field.addEventListener("change", () => {
			validateField(fieldName);
			hideSuccess();
		});
	});

	const serviceCheckboxes = form.querySelectorAll('input[name="services"]');
	serviceCheckboxes.forEach((checkbox) => {
		checkbox.addEventListener("change", () => {
			validateServices();
			hideSuccess();
		});
	});

	form.addEventListener("submit", (event) => {
		event.preventDefault();
		hideSuccess();

		const isValid = validateForm();
		if (!isValid) {
			const firstInvalid = form.querySelector("[aria-invalid='true']");
			if (firstInvalid) {
				firstInvalid.focus();
			}
			return;
		}

		successMessage.textContent =
			"Aplicacion enviada correctamente. Nuestro equipo revisara tus datos y te contactara en menos de 48 horas.";
		successMessage.classList.remove("hidden");
		form.reset();
		fields.forEach((fieldName) => {
			const field = form.elements[fieldName];
			if (field) clearFieldError(field);
		});
		clearServicesError();
	});

	clearButton.addEventListener("click", () => {
		fields.forEach((fieldName) => {
			const field = form.elements[fieldName];
			if (field) clearFieldError(field);
		});
		clearServicesError();
		hideSuccess();
	});
}
