// Gemeinsames JavaScript für alle Seiten. Wird vor Alpine.js geladen.

(function () {
    const media = window.matchMedia('(prefers-color-scheme: dark)');

    function storedTheme() {
        try {
            return localStorage.getItem('theme') || 'auto';
        } catch (e) {
            return 'auto';
        }
    }

    function applyTheme(choice) {
        const dark = choice === 'dark' || (choice !== 'light' && media.matches);
        document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    }

    // System-Farbschema folgen, solange "Auto" gewählt ist
    media.addEventListener('change', () => {
        if (storedTheme() === 'auto') applyTheme('auto');
    });

    document.addEventListener('alpine:init', () => {
        // Farbschema-Umschalter: Hell / Dunkel / Auto
        Alpine.data('themeSwitcher', () => ({
            open: false,
            choice: storedTheme(),
            set(choice) {
                this.open = false;
                this.choice = choice;
                try {
                    localStorage.setItem('theme', choice);
                } catch (e) {}
                applyTheme(choice);
            },
        }));

        // Push-Benachrichtigungen für dieses Gerät ein-/ausschalten (Profilseite)
        Alpine.data('pushToggle', (cfg) => ({
            // unsupported | ios-install | denied | off | on
            state: 'off',
            busy: false,
            message: '',
            async init() {
                const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
                const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
                if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
                    // iOS kennt Web Push nur in der installierten App (Home-Bildschirm)
                    this.state = ios && !standalone ? 'ios-install' : 'unsupported';
                    return;
                }
                if (Notification.permission === 'denied') {
                    this.state = 'denied';
                    return;
                }
                const reg = await navigator.serviceWorker.ready;
                this.state = (await reg.pushManager.getSubscription()) ? 'on' : 'off';
            },
            async post(url, body) {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cfg.csrf },
                    body: JSON.stringify(body || {}),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.error || 'Serverfehler');
                return data;
            },
            async enable() {
                this.busy = true;
                this.message = '';
                try {
                    if (await Notification.requestPermission() !== 'granted') {
                        this.state = Notification.permission === 'denied' ? 'denied' : 'off';
                        return;
                    }
                    const reg = await navigator.serviceWorker.ready;
                    const sub = await reg.pushManager.subscribe({
                        userVisibleOnly: true,
                        applicationServerKey: urlBase64ToUint8Array(cfg.publicKey),
                    });
                    await this.post(cfg.subscribeUrl, sub.toJSON());
                    this.state = 'on';
                } catch (e) {
                    this.message = 'Aktivieren fehlgeschlagen: ' + e.message;
                } finally {
                    this.busy = false;
                }
            },
            async disable() {
                this.busy = true;
                this.message = '';
                try {
                    const reg = await navigator.serviceWorker.ready;
                    const sub = await reg.pushManager.getSubscription();
                    if (sub) {
                        await this.post(cfg.unsubscribeUrl, { endpoint: sub.endpoint });
                        await sub.unsubscribe();
                    }
                    this.state = 'off';
                } catch (e) {
                    this.message = 'Deaktivieren fehlgeschlagen: ' + e.message;
                } finally {
                    this.busy = false;
                }
            },
            async test() {
                this.busy = true;
                this.message = '';
                try {
                    await this.post(cfg.testUrl);
                    this.message = 'Test-Benachrichtigung gesendet.';
                } catch (e) {
                    this.message = e.message;
                } finally {
                    this.busy = false;
                }
            },
        }));

        // Merken und Melden von Fragen auf Seiten mit mehreren Fragen (Auswertung, Nachschlagen).
        // cfg: urls {bookmark, report} mit Platzhalter-ID 0, saved {id: true} für bereits gemerkte Fragen
        Alpine.data('questionActions', (cfg) => questionActionsData(cfg));

        // Fragen-Durchgang (Theorie-Training, Prüfung): Blättern läuft im Browser, abgegeben wird per Formular.
        // cfg: questions [{id, label, question, help, choices: [[buchstabe, text]]}],
        //      storageKey (Zwischenstand, eindeutig je Durchgang), storagePrefix, persistent (localStorage statt sessionStorage)
        //      optional: initialAnswers (Stand vom Server), autosave (Antworten beim Blättern an den Server schicken),
        //      remaining (Sekunden bis zur automatischen Abgabe)
        Alpine.data('questionRun', (cfg) => ({
            // Merken/Melden nur im Training (cfg.urls gesetzt)
            ...questionActions(cfg.urls || {}),
            questions: cfg.questions,
            index: 0,
            answers: {},
            hint: false,
            submitting: false,
            timeLeft: null,
            init() {
                const store = runStore(cfg.persistent);
                store.prune(cfg.storagePrefix, cfg.storageKey);
                const saved = store.read(cfg.storageKey) || {};
                const savedAnswers = saved.answers || cfg.initialAnswers || {};
                this.questions.forEach((q) => {
                    const prev = savedAnswers[q.id];
                    this.answers[q.id] = Array.isArray(prev) ? prev.filter((x) => q.choices.some((c) => c[0] === x)) : [];
                });
                this.questions.forEach((q) => {
                    if (q.saved) this.saved[q.id] = true;
                });
                this.index = Math.min(Math.max(parseInt(saved.index, 10) || 0, 0), this.questions.length - 1);
                this.store = store;
                // Erst nach dem Aufbau der Kinder starten: bei Restzeit 0 wird sofort abgegeben (braucht $refs)
                if (cfg.remaining != null) this.$nextTick(() => this.startTimer(cfg.remaining));
                // Zurück aus dem bfcache nach einer Abgabe: Seite neu laden statt gesperrter Buttons
                window.addEventListener('pageshow', (event) => {
                    if (event.persisted && this.submitting) window.location.reload();
                });
                if (cfg.autosave) {
                    // Beim Verlassen/Wegschalten der Seite den Stand sichern
                    document.addEventListener('visibilitychange', () => {
                        if (document.visibilityState === 'hidden') this.sync(true);
                    });
                }
                this.$watch('index', () => {
                    this.hint = false;
                    this.closeReport();
                    this.persist();
                    this.sync();
                    this.$nextTick(() => {
                        window.scrollTo(0, 0);
                        if (this.$refs.heading) this.$refs.heading.focus({ preventScroll: true });
                    });
                });
            },
            get q() { return this.questions[this.index]; },
            // Antworten der aktuellen Frage samt Fragen-ID. In x-for nur diese Werte nutzen, nicht den Getter q:
            // Alpine wertet Getter im Schleifen-Scope ab dem 2. Eintrag ohne Komponenten-Kontext aus
            // (dann ist q undefined und nur Antwort A erscheint).
            get options() {
                const q = this.q;
                return q ? q.choices.map(([letter, text]) => ({ key: `${q.id}-${letter}`, qid: q.id, letter, text })) : [];
            },
            get total() { return this.questions.length; },
            get isLast() { return this.index === this.questions.length - 1; },
            get progress() { return Math.round((this.index / this.questions.length) * 100); },
            get answeredCount() { return this.questions.filter((q) => this.answers[q.id].length).length; },
            persist() {
                this.store.write(cfg.storageKey, { index: this.index, answers: this.answers });
            },
            // Zwischenstand an den Server (nur mit cfg.autosave); Fehler stören das Weiterarbeiten nicht
            sync(beacon) {
                if (!cfg.autosave || this.submitting) return;
                const data = new FormData();
                data.append('csrfmiddlewaretoken', this.$refs.form.querySelector('[name=csrfmiddlewaretoken]').value);
                data.append('action', 'save');
                data.append('answers', JSON.stringify(this.answers));
                if (beacon && navigator.sendBeacon) {
                    navigator.sendBeacon(this.$refs.form.action, data);
                } else {
                    fetch(this.$refs.form.action, { method: 'POST', body: data, credentials: 'same-origin', keepalive: true })
                        .catch(() => {});
                }
            },
            startTimer(seconds) {
                // Restzeit vom Server ab Seitenaufruf rechnen: eine falsch gehende Geräteuhr spielt keine Rolle
                const deadline = Date.now() + seconds * 1000;
                const tick = () => {
                    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
                    this.timeLeft = left;
                    if (left <= 0) this.submit();
                    else setTimeout(tick, 1000);
                };
                tick();
            },
            get timeLabel() {
                if (this.timeLeft == null) return '--:--';
                return String(Math.floor(this.timeLeft / 60)).padStart(2, '0') + ':' + String(this.timeLeft % 60).padStart(2, '0');
            },
            back() {
                if (this.index > 0) this.index--;
            },
            next() {
                if (this.isLast) this.submit();
                else this.index++;
            },
            submit() {
                if (this.submitting) return;
                this.submitting = true;
                window.pageFeedback.start();
                this.persist();
                this.$refs.answers.value = JSON.stringify(this.answers);
                this.$refs.form.submit();
            },
        }));
    });

    // ── Rückmeldung ──────────────────────────────────────────────────────────
    // Seitenwechsel (Links, Formulare) zeigen einen Ladebalken oben; der gedrückte Knopf bekommt einen Spinner
    // und lässt sich nicht erneut auslösen. Ein Formular wird nur einmal abgeschickt (Doppelklick).
    // Ausnahmen: data-no-progress, download, target=_blank, Links innerhalb der Seite.
    const pageFeedback = (function () {
        const SHOW_DELAY = 150;      // schnelle Seitenwechsel (vorgeladen) ohne Aufblitzen
        const FALLBACK_RESET = 20000; // falls keine neue Seite kommt (z.B. Datei-Antwort, Abbruch)
        let showTimer = null;
        let resetTimer = null;

        function bar() {
            return document.getElementById('page-progress');
        }

        function start() {
            clearTimeout(showTimer);
            clearTimeout(resetTimer);
            showTimer = setTimeout(() => bar() && bar().classList.add('is-active'), SHOW_DELAY);
            resetTimer = setTimeout(reset, FALLBACK_RESET);
        }

        function markBusy(el) {
            if (!el || el.classList.contains('is-loading')) return;
            el.classList.add('is-loading');
            el.setAttribute('aria-busy', 'true');
            const spinner = document.createElement('span');
            spinner.className = 'spinner js-feedback-spinner';
            spinner.setAttribute('aria-hidden', 'true');
            el.prepend(spinner);
        }

        function reset() {
            clearTimeout(showTimer);
            clearTimeout(resetTimer);
            if (bar()) bar().classList.remove('is-active');
            document.querySelectorAll('.js-feedback-spinner').forEach((el) => el.remove());
            document.querySelectorAll('.is-loading').forEach((el) => {
                el.classList.remove('is-loading');
                el.removeAttribute('aria-busy');
            });
            document.querySelectorAll('form[data-busy]').forEach((form) => delete form.dataset.busy);
        }

        function isPageLink(link, event) {
            if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
            if (link.hasAttribute('download') || link.hasAttribute('data-no-progress')) return false;
            if (link.target && link.target !== '_self') return false;
            const url = new URL(link.href, location.href);
            if (url.origin !== location.origin || !/^https?:$/.test(url.protocol)) return false;
            // Sprung innerhalb derselben Seite
            if (url.pathname === location.pathname && url.search === location.search && url.hash) return false;
            return true;
        }

        document.addEventListener('click', (event) => {
            const link = event.target.closest && event.target.closest('a[href]');
            if (!link || !isPageLink(link, event)) return;
            start();
            if (link.classList.contains('btn')) markBusy(link);
        });

        document.addEventListener('submit', (event) => {
            const form = event.target;
            if (event.defaultPrevented || form.hasAttribute('data-no-progress') || (form.target && form.target !== '_self')) return;
            if (form.dataset.busy) {
                event.preventDefault(); // schon unterwegs
                return;
            }
            form.dataset.busy = '1';
            start();
            const button = event.submitter || form.querySelector('button[type=submit], button:not([type])');
            if (button && button.classList.contains('btn')) markBusy(button);
        });

        // Zurück-Taste (bfcache): Seite ohne hängende Spinner zeigen
        window.addEventListener('pageshow', reset);

        return { start, reset, markBusy };
    })();
    window.pageFeedback = pageFeedback;

    // POST mit JSON an die eigene Seite; CSRF-Token aus einem beliebigen Formular der Seite
    // (base.html enthält für angemeldete Nutzer immer das Abmelde-Formular)
    async function postJSON(url, body) {
        const token = document.querySelector('[name=csrfmiddlewaretoken]');
        const res = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.value : '' },
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Das hat nicht geklappt. Bitte später erneut versuchen.');
        return data;
    }

    // Gemeinsamer Teil für „Merken“ und „Fehler melden“ (in questionRun und questionActions eingemischt).
    // urls: {bookmark, report}, jeweils mit der Platzhalter-ID 0
    function questionActions(urls) {
        return {
            saved: {},
            report: { openId: null, text: '', error: '', busy: false, sent: {} },
            actionUrl(kind, id) {
                return urls[kind].replace('/0/', `/${id}/`);
            },
            isSaved(id) {
                return !!this.saved[id];
            },
            async toggleSave(id) {
                const want = !this.saved[id];
                this.saved[id] = want; // sofort anzeigen, bei Fehler zurücknehmen
                try {
                    this.saved[id] = (await postJSON(this.actionUrl('bookmark', id), { saved: want })).saved;
                } catch (e) {
                    this.saved[id] = !want;
                    window.alert(e.message);
                }
            },
            openReport(id) {
                this.report.openId = id;
                this.report.text = '';
                this.report.error = '';
            },
            closeReport() {
                this.report.openId = null;
            },
            async sendReport(id) {
                if (this.report.busy || !this.report.text.trim()) return;
                this.report.busy = true;
                this.report.error = '';
                try {
                    await postJSON(this.actionUrl('report', id), { message: this.report.text });
                    this.report.sent[id] = true;
                    this.report.openId = null;
                } catch (e) {
                    this.report.error = e.message;
                } finally {
                    this.report.busy = false;
                }
            },
        };
    }

    // Zustand für Merken/Melden als einfaches Objekt: auch in eigene x-data-Objekte einmischbar
    function questionActionsData(cfg) {
        return { ...questionActions(cfg.urls), saved: { ...(cfg.saved || {}) } };
    }
    window.questionActionsData = questionActionsData;

    // Zwischenstand eines Fragen-Durchgangs im Browser (Fehler beim Speicher werden ignoriert)
    function runStore(persistent) {
        let area = null;
        try {
            area = persistent ? window.localStorage : window.sessionStorage;
        } catch (e) {}
        return {
            read(key) {
                try {
                    return JSON.parse(area.getItem(key));
                } catch (e) {
                    return null;
                }
            },
            write(key, value) {
                try {
                    area.setItem(key, JSON.stringify(value));
                } catch (e) {}
            },
            // Alte Durchgänge gleicher Art entfernen
            prune(prefix, keep) {
                try {
                    for (let i = area.length - 1; i >= 0; i--) {
                        const key = area.key(i);
                        if (key && key.startsWith(prefix) && key !== keep) area.removeItem(key);
                    }
                } catch (e) {}
            },
        };
    }

    function urlBase64ToUint8Array(base64) {
        const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
        return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
    }
})();
