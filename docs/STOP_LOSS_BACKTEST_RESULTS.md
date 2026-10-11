# TradingBotR1000 — Risultati dei backtest sugli stop loss

Aggiornato: 2026-10-11. Documento di ricerca; non modifica la strategia operativa PAPER o LIVE.

## Provenienza e ambito

Le simulazioni sono state eseguite dall'utente sul PC Windows, progetto C:\TradingbotR1000, e i risultati sono stati comunicati in chat. Questo documento consolida quei risultati sul server. I CSV completi e il motore Windows non sono stati trasferiti sul server con questa registrazione.

Non è stato trovato sul server un documento dedicato ai risultati degli stop. La documentazione precedente menzionava l'esito sfavorevole del test al 3% nella Master History e in docs/LIVE_GO_LIVE_RUNBOOK_2026-09-24.md. I report delle singole simulazioni già esistenti sul PC sono conservati e referenziati sotto; questo documento ne raccoglie il confronto.

Fonte del test al 3%: risultato precedente registrato nella conversazione. Fonti dei nuovi test al 4% e 0,5%: output di comparison_summary.csv, log di esecuzione e frammenti del motore forniti dall'utente il 2026-10-11. I risultati sono simulati, non rendimenti realizzati dal conto IBKR.

## Configurazione comune

- Periodo di simulazione: 2017-05-19–2026-07-21, circa 9 anni e 2 mesi, su archivio storico di circa dieci anni. Il periodo iniziale è usato per il riscaldamento degli indicatori.
- Capitale iniziale: USD 1.000.000.
- Universo: snapshot corrente IWB/Russell 1000, 979 simboli nel caricamento; esclusioni e alias definiti nella configurazione. Non sono ricostruiti i componenti storici dell'indice.
- Barre giornaliere OHLCV (apertura, massimo, minimo, chiusura, volume).
- Ingresso: chiusura sopra media mobile semplice a 200 sedute e sotto banda di Bollinger inferiore a 20 sedute / 2,5 deviazioni standard.
- Ordine BUY LIMIT DAY nella seduta successiva, limite pari al 97% della chiusura del segnale, arrotondato ai centesimi.
- Ranking: apprezzamento del prezzo su 150 sedute.
- Massimo 5 posizioni; allocazione target 20% del patrimonio per posizione; margine di sicurezza sul cash 1%; nessuna leva.
- Uscita baseline: RSI (Relative Strength Index) a 2 sedute attraversa verso l'alto 60, oppure 10 sedute detenute; vendita all'apertura successiva. Il giorno d'ingresso conta come prima seduta.
- Stop delle varianti: fisso, rispetto al prezzo d'ingresso simulato, attivo anche nella seduta d'acquisto; non è trailing.
- CONFIGURED_SLIPPAGE: 5 punti base = 0,05% di scostamento sfavorevole per acquisto e per vendita.
- ZERO_SLIPPAGE: nessuno scostamento aggiuntivo sui prezzi teorici. I gap all'apertura restano modellati.
- Commissioni configurate: zero. I costi reali non sono quindi riprodotti integralmente.
- Il CAGR del motore usa numero di barre di portafoglio / 252 come durata annualizzata.

I test di oggi hanno copiato config_snapshot.json del run originale, cambiando soltanto percentuale dello stop e identificativi dello studio/scenario. Le cartelle precedenti non sono state sovrascritte. Il baseline con slippage è stato riprodotto esattamente nei due nuovi run: capitale finale USD 3.324.659,6407536212 e 561 trade chiusi.

## Confronto principale — slippage 0,05% per lato

| Variante | Capitale finale USD | Rendimento totale | CAGR | Massimo drawdown | Sharpe | Trade chiusi | Trade vincenti |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline senza stop | 3.324.659,64 | 232,47% | 14,04% | -22,92% | 0,8983 | 561 | 63,28% |
| Stop 3% — test precedente | 1.273.931,71 | 27,39% | 2,68% | -18,53% | 0,294 | 731 | 40,77% |
| Stop 4% — 2026-10-11 | 1.395.077,59 | 39,51% | 3,71% | -23,77% | 0,3668 | 690 | 48,41% |
| Stop 0,5% — 2026-10-11 | 1.062.763,52 | 6,28% | 0,67% | -7,97% | 0,1664 | 867 | 9,11% |

Tutte le soglie fisse finora testate riducono il rendimento rispetto al baseline. Lo stop 0,5% riduce il drawdown, accompagnato da permanenza ed esposizione a fine giornata molto inferiori. Lo stop 4% non migliora neppure il massimo drawdown nel confronto con slippage. Questi risultati non dimostrano che ogni possibile stop sia inefficace.

## Confronto senza slippage — output di oggi

| Variante | Capitale finale USD | Rendimento totale | CAGR | Massimo drawdown | Sharpe | Trade chiusi | Trade vincenti |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline senza stop | 3.720.275,76 | 272,03% | 15,45% | -21,61% | 0,9751 | 561 | 64,17% |
| Stop 4% | 1.611.934,80 | 61,19% | 5,36% | -21,30% | 0,5022 | 687 | 48,76% |
| Stop 0,5% | 1.207.106,93 | 20,71% | 2,08% | -6,19% | 0,4635 | 866 | 9,47% |

Non è stata fornita oggi la riga ZERO_SLIPPAGE del vecchio test al 3%; non viene ricostruita. Il peggioramento di rendimento degli stop 4% e 0,5% permane anche senza slippage, quindi non è spiegato soltanto da quel costo.

## Dettagli dei run di oggi

| Metrica | Baseline con slippage | Stop 4% con slippage | Stop 0,5% con slippage |
| --- | ---: | ---: | ---: |
| Acquisti eseguiti | 562 | 691 | 868 |
| Rendimento medio per trade | 1,1285% | 0,2789% | 0,0365% |
| Rendimento mediano per trade | 1,4682% | -1,1898% | -0,54975% |
| Durata media riportata, sedute | 6,6132 | 4,2362 | 1,5894 |
| Esposizione media a fine giornata | 27,0258% | 19,4680% | 4,5299% |
| Cash medio a fine giornata | 72,9742% | 80,5320% | 95,4701% |
| Stop eseguiti | 0 | 335 | 788 |
| Stop su gap all'apertura | 0 | 30 | 27 |
| Stop nella seduta d'acquisto | 0 | 84 | 657 |
| Trade marcati ambigui dal motore | 0 | 8 | 2 |
| Trade marcati con split durante la posizione | 0 | 0 | 0 |

L'esposizione è misurata sul portafoglio a fine giornata e non include tutta l'esposizione intraday di acquisti e vendite avvenuti nella stessa seduta. Il numero di acquisti supera di uno quello dei trade chiusi in ciascuna riga, coerentemente con una posizione ancora aperta a fine periodo; il suo valore di mercato concorre al patrimonio finale.

Nel test allo 0,5%, 657/867 = 75,78% dei trade chiusi sono stoppati nella seduta d'acquisto. Tra le 788 uscite per stop, 657/788 = 83,38% avvengono nella seduta d'acquisto.

## Analisi MAE e richiesta della soglia del 70%

Definizione scelta dall'utente il 2026-10-11: “non recuperato” significa trade chiuso in perdita secondo le regole del bot, senza stop; non significa che il prezzo non abbia mai ritoccato il pareggio.

La MAE (Maximum Adverse Excursion, massima discesa sfavorevole) è misurata dal prezzo d'ingresso durante la posizione. Analisi effettuata sui trade chiusi PRODUCTION_BASELINE / CONFIGURED_SLIPPAGE, non su tutti i candidati acquistabili e non su ciascun titolo separatamente.

| Discesa raggiunta | Trade | Chiusi in perdita | Percentuale perdenti |
| --- | ---: | ---: | ---: |
| -0,5% | 511 | 206 | 40,31% |
| -1% | 472 | 206 | 43,64% |
| -2% | 390 | 204 | 52,31% |
| -3% | 321 | 198 | 61,68% |
| -3,5% | 289 | 190 | 65,74% |
| -4% | 263 | 185 | 70,34% |
| -5% | 213 | 159 | 74,65% |
| -6% | 177 | 141 | 79,66% |
| -8% | 132 | 112 | 84,85% |
| -10% | 85 | 76 | 89,41% |

Il -4% è la prima soglia della griglia a incrementi di 0,5 punti percentuali che raggiunge il 70%. È una descrizione dell'intero campione storico, non una soglia ottimizzata o validata fuori campione.

### Perché 70% perdenti non implica stop conveniente

Ulteriore analisi dei 263 trade baseline con MAE <= -4%:

| Esito finale senza stop | Numero | Rendimento finale medio |
| --- | ---: | ---: |
| Chiusura senza perdita | 78 | +3,86% |
| Perdita inferiore a -4,048% | 101 | -1,80% |
| Perdita uguale o superiore a -4,048% | 84 | -8,75% |

Nella seconda riga “inferiore” indica una perdita meno grave: rendimento compreso tra -4,048% e 0%.

Per uno stop ordinario alla soglia 4%, il modello produce un rendimento netto circa -4,048%: 0,96 × (1 - 0,0005) - 1. Il riferimento è il prezzo d'ingresso già comprensivo dello slippage d'acquisto. Gap e commissioni eventuali possono peggiorare il risultato.

179/263 = 68,06% dei trade baseline raggiunti da quella soglia hanno un esito finale migliore del riferimento -4,048%; solo 84/263 = 31,94% sono potenziali beneficiari prima dei gap. Questa classificazione non è un'attribuzione monetaria esatta del portafoglio stop: le uscite anticipate cambiano capitale, quantità e acquisti successivi, e i gap possono cambiare il prezzo di vendita.

## Controlli e limiti dell'audit del 2026-10-11

- Nei run 4% e 0,5% l'utente ha comunicato 9/9 test sintetici del motore passati e verification_all_passed=True.
- I test condivisi del motore sono stati eseguiti prima di impostare la nuova percentuale nella configurazione. Provano i casi sintetici presenti nella suite; non sono una validazione completa, specifica per ciascuna soglia, del mercato o dei dati.
- Controllati i frammenti run_backtest.py forniti: stop_price = entry_price × (1-stop_loss_pct); vendite programmate all'apertura prima degli stop; prezzi di apertura usati per i gap; slippage applicato in senso sfavorevole; calcolo del cash e del P&L.
- Tre prove indipendenti sui frammenti forniti: stop nella seduta d'ingresso con rendimento -4,048% e cash riconciliato; acquisto migliorato all'apertura con successivo gap-stop; uscita programmata all'apertura senza utilizzo del minimo successivo per uscita/MAE. Tutte coerenti nei casi costruiti.
- Nessun errore identificato in quei meccanismi che spieghi la caduta del rendimento. Questo non certifica tutti i trade storici, i dati o ogni funzione del motore.
- Problema rilevato nella metrica profit_factor: il motore usa la somma dei rendimenti net_return, non la somma dei profitti/perdite monetari net_pnl. La metrica è quindi riferita ai rendimenti dei trade e non al profit factor monetario standard. Non causa il patrimonio finale osservato; correzione non ancora applicata. Per evitare ambiguità, non è usata nelle tabelle principali.
- Il caricatore legge i prezzi presenti nei CSV e gli split come date da segnalare; non applica qui rettifiche ai prezzi/quantità. La correttezza delle rettifiche deve essere garantita e verificata a monte. Zero split durante i trade non certifica l'intera storia degli indicatori.
- Barre giornaliere: non riproducono sequenza completa degli scambi, spread, coda degli ordini, volume disponibile al limite o ritardo di attivazione dello stop. Il raggiungimento del limite viene trattato come fill.
- Slippage d'acquisto modellato come prezzo maggiorato anche quando il fill teorico avviene al limite: ipotesi economica di costo, non riproduzione letterale della garanzia di prezzo di un ordine limite.
- Universo corrente: rischio di survivorship bias e di storia societaria/ticker non comparabile.
- La scelta della soglia è stata effettuata sullo stesso campione dei confronti successivi. Non è stata eseguita una validazione fuori campione o walk-forward.

## Percorsi degli output originali sul PC

1. Test precedente 3%:
   C:\TradingbotR1000\backtests\production_baseline_stoploss_3pct\runs\run_20260923_203718
2. Test 4%:
   C:\TradingbotR1000\backtests\production_baseline_stoploss_4pct\runs\run_20261011_151041
3. Test 0,5%:
   C:\TradingbotR1000\backtests\production_baseline_stoploss_0p5pct\runs\run_20261011_152858

File principali: comparison_summary.csv, trades.csv, portfolio_daily.csv, candidate_audit.csv, orders.csv, config_snapshot.json, dataset_audit.json, dataset_audit_files.csv, verification.json, execution.log e REPORT.md. Nel vecchio run 3% sono presenti anche STOP_DIAGNOSTIC_REPORT.md e stopped_trade_counterfactuals.csv.

Le copie dei runner derivano dal programma originariamente denominato 3pct. Alcuni titoli/campi descrittivi possono ancora riferirsi al 3% (per esempio trades_mae_below_minus_3pct). Per il parametro effettivamente simulato fanno fede config_snapshot.json, stop_price e gli scenari PRODUCTION_PLUS_STOP_4 / PRODUCTION_PLUS_STOP_0P5.

## Conclusione e attività ancora aperte

Risultato registrato: nei confronti svolti nessuna delle soglie fisse 3%, 4% e 0,5% migliora il rendimento del baseline. La soglia del 70% di esiti perdenti non è un criterio sufficiente di convenienza economica dello stop. Nessuna nuova soglia è stata approvata o applicata al bot operativo.

Eventuali sviluppi: attribuire esattamente perdite evitate e recuperi/profitti sacrificati; correggere o rinominare profit_factor; studiare tutti i candidati acquistabili e la MAE per titolo con numero di osservazioni; valutare soglie legate alla volatilità e validazione fuori campione. Queste attività non sono state eseguite con la registrazione di oggi.
