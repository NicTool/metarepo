ARG RUNTIME=node:24
FROM ${RUNTIME}

WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .

CMD ["npm", "test"]
