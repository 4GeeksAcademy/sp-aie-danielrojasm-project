# Contenedor de interfaces para desarrollo: website (:3000) y backoffice (:3001)
# con `next dev`. El código llega por bind mount desde docker-compose.yml; la
# imagen solo aporta Node y las dependencias de cada app.
FROM node:24-alpine

WORKDIR /app/uis

# Cada app es un proyecto npm independiente (sin workspaces): se instala por
# separado para que un cambio en un lockfile no invalide la caché de la otra.
COPY website/package.json website/package-lock.json ./website/
RUN npm ci --prefix website

COPY backoffice/package.json backoffice/package-lock.json ./backoffice/
RUN npm ci --prefix backoffice

COPY . .

EXPOSE 3000 3001

CMD ["sh", "./start.sh"]
