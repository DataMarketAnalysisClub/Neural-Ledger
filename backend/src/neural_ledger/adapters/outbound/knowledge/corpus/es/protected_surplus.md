---
{
  "id": "protected_surplus",
  "lang": "es",
  "title": "Excedente protegido",
  "aliases": ["lo que realmente tengo disponible", "plata disponible", "protected surplus"],
  "tags": ["neural ledger", "flujo de caja", "ahorro"],
  "related": ["liquidity_floor", "emergency_fund", "installments"],
  "sources": [
    {"title": "Neural Ledger Financial Core", "url": "https://github.com/DataMarketAnalysisClub/Neural-Ledger/blob/main/docs/FINANCIAL_CORE.md", "license": "project documentation"}
  ],
  "numbers": []
}
---
Tu excedente protegido es la plata que podría salir hoy de tu cuenta sin que ningún mes del pronóstico conservador quede bajo tu saldo mínimo.

No es el saldo que ves en la cuenta. Parte de ese saldo ya está comprometido: el arriendo, las cuentas, el pago de la tarjeta y las cuotas de compras anteriores que vencen en los próximos meses. El excedente protegido mira hacia adelante en todo el horizonte del pronóstico, descuenta lo que ya está comprometido y guarda un colchón para los meses que suelen salir más caros que el promedio.

El pronóstico es conservador a propósito: supone que tus ingresos llegan un poco más bajos y tus gastos un poco más altos de lo habitual. Por eso la cifra es menor que un simple "ingresos menos gastos".

Dos cosas lo mueven:

- Un compromiso nuevo, como una compra en cuotas, lo baja en cada mes en que se paga.
- Un saldo mínimo más alto (tu piso de liquidez) también lo baja, porque más plata tiene que quedarse en la cuenta.

El excedente protegido es una estimación hecha con tu propio historial, no una promesa sobre el futuro. Es información general sobre cómo el copiloto mide lo disponible, no una recomendación de gastar o ahorrar un monto específico.
