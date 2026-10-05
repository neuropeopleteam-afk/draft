# ФСП ID (демо): Keycloak с оптимизированной сборкой под PostgreSQL и путь /auth, realm fsp импортируется при старте.
FROM quay.io/keycloak/keycloak:26.4.0 AS builder
ENV KC_DB=postgres \
    KC_HTTP_RELATIVE_PATH=/auth \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=false \
    KC_CACHE=local
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.4.0
COPY --from=builder /opt/keycloak/ /opt/keycloak/
COPY realm-fsp.json /opt/keycloak/data/import/realm-fsp.json
ENV KC_CACHE=local
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--optimized", "--import-realm"]
