// Gemeinsames JavaScript für alle Seiten. Wird vor Alpine.js geladen.

(function () {
    const media = window.matchMedia('(prefers-color-scheme: dark)');

    // Installationsangebot des Browsers (Android, Desktop) für den Knopf „App installieren“ aufheben
    let installEvent = null;
    window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        installEvent = event;
        window.dispatchEvent(new CustomEvent('la:install-available'));
    });
    window.addEventListener('appinstalled', () => {
        installEvent = null;
        window.dispatchEvent(new CustomEvent('la:installed'));
    });

    function isStandalone() {
        return window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
    }

    function isIOS() {
        return /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    }

    function storageGet(key) {
        try {
            return localStorage.getItem(key);
        } catch (e) {
            return null;
        }
    }

    function storageSet(key, value) {
        try {
            if (value === null) localStorage.removeItem(key);
            else localStorage.setItem(key, value);
        } catch (e) {}
    }

    // ── Hinweise (Toasts) ────────────────────────────────────────────────────
    // toast(text, {level: 'success'|'info'|'warning'|'error', action: {label, run}, sticky})
    // Fehler und Hinweise mit Knopf bleiben stehen, alles andere verschwindet nach TOAST_MS.
    const TOAST_MS = 5000;
    function toast(text, options = {}) {
        window.dispatchEvent(new CustomEvent('la:toast', { detail: { text, ...options } }));
    }
    window.toast = toast;

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
        // Hinweis-Stapel unten (Django-Meldungen der Seite und toast() aus dem Code)
        Alpine.data('toastStack', () => ({
            items: [],
            nextId: 1,
            init() {
                // Django-Meldungen der Seite (base.html, #flash-messages)
                document.querySelectorAll('#flash-messages li').forEach((li) => {
                    this.add({ text: li.textContent, level: li.dataset.level });
                });
                window.addEventListener('la:toast', (event) => this.add(event.detail));
            },
            add(item) {
                const entry = { id: this.nextId++, level: 'info', ...item };
                this.items.push(entry);
                if (!entry.sticky && !entry.action && entry.level !== 'error') {
                    setTimeout(() => this.remove(entry.id), TOAST_MS);
                }
            },
            remove(id) {
                this.items = this.items.filter((item) => item.id !== id);
            },
            run(item) {
                this.remove(item.id);
                item.action.run();
            },
        }));

        // Verbindungsstatus für die Leiste „Keine Verbindung“
        Alpine.data('connection', () => ({
            online: navigator.onLine,
            init() {
                window.addEventListener('online', () => { this.online = true; });
                window.addEventListener('offline', () => { this.online = false; });
            },
        }));

        // Knopf/Karte „App installieren“: Android/Desktop über den Browser-Dialog, iOS mit Anleitung.
        // dismissKey: optional, „Nicht mehr zeigen“ wird im Gerät gemerkt
        Alpine.data('installPrompt', (cfg = {}) => ({
            // hidden | available | ios
            mode: 'hidden',
            help: false,
            init() {
                const update = () => {
                    if (isStandalone() || (cfg.dismissKey && storageGet(cfg.dismissKey))) this.mode = 'hidden';
                    else if (installEvent) this.mode = 'available';
                    else if (isIOS()) this.mode = 'ios';
                    else this.mode = 'hidden';
                };
                update();
                window.addEventListener('la:install-available', update);
                window.addEventListener('la:installed', update);
            },
            async install() {
                if (this.mode === 'ios') {
                    this.help = !this.help;
                    return;
                }
                if (!installEvent) return;
                installEvent.prompt();
                const choice = await installEvent.userChoice.catch(() => null);
                installEvent = null;
                this.mode = 'hidden';
                if (choice && choice.outcome === 'accepted') toast('Die App wird installiert.', { level: 'success' });
            },
            dismiss() {
                if (cfg.dismissKey) storageSet(cfg.dismissKey, '1');
                this.mode = 'hidden';
            },
        }));

        // Nach dem ersten Training: Erinnerungen per Push anbieten (nur wenn noch nie gefragt)
        Alpine.data('pushPrompt', (cfg) => ({
            show: false,
            busy: false,
            async init() {
                if (storageGet('push-prompt-answered') || !pushSupported() || Notification.permission !== 'default') return;
                const reg = await navigator.serviceWorker.ready;
                this.show = !(await reg.pushManager.getSubscription());
            },
            async accept() {
                this.busy = true;
                try {
                    const state = await subscribePush(cfg);
                    if (state === 'on') toast('Erinnerungen sind eingeschaltet.', { level: 'success' });
                    else if (state === 'denied') toast('Benachrichtigungen sind im Browser blockiert.', { level: 'warning' });
                } catch (e) {
                    toast('Einschalten fehlgeschlagen: ' + e.message, { level: 'error' });
                } finally {
                    this.busy = false;
                    this.decline();
                }
            },
            decline() {
                storageSet('push-prompt-answered', '1');
                this.show = false;
            },
        }));

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
                if (!pushSupported()) {
                    // iOS kennt Web Push nur in der installierten App (Home-Bildschirm)
                    this.state = isIOS() && !isStandalone() ? 'ios-install' : 'unsupported';
                    return;
                }
                if (Notification.permission === 'denied') {
                    this.state = 'denied';
                    return;
                }
                this.state = await syncPushSubscription(cfg);
                // Berechtigung später in den Browser-Einstellungen geändert: Schalter nachziehen
                if (navigator.permissions && navigator.permissions.query) {
                    navigator.permissions.query({ name: 'notifications' }).then((status) => {
                        status.onchange = async () => {
                            this.state = Notification.permission === 'denied' ? 'denied' : await syncPushSubscription(cfg);
                        };
                    }).catch(() => {});
                }
            },
            async post(url, body) {
                return postJSON(url, body);
            },
            async enable() {
                this.busy = true;
                this.message = '';
                try {
                    this.state = await subscribePush(cfg);
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
                // Bildschirm während des Durchgangs nicht abschalten
                keepScreenOn();
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
            waitingForNetwork: false,
            submit() {
                if (this.submitting) return;
                this.persist();
                if (!navigator.onLine) {
                    if (cfg.offlineQueue) {
                        // Training: Antworten auf dem Gerät aufheben und senden, sobald wieder Netz da ist
                        queueTraining({
                            user: document.body.dataset.user,
                            url: this.$refs.form.action,
                            run_id: cfg.offlineQueue.runId,
                            question_ids: this.questions.map((q) => q.id),
                            answers: this.answers,
                        });
                        this.waitingForNetwork = true;
                        this.submitting = true;
                        toast('Keine Verbindung: Deine Antworten sind gespeichert und werden gesendet, sobald du wieder online bist.', { level: 'warning', sticky: true });
                    } else {
                        // Prüfung: der Zwischenstand liegt schon auf dem Server (Autosave)
                        toast('Keine Verbindung. Deine Antworten sind zwischengespeichert – gib ab, sobald du wieder online bist.', { level: 'warning' });
                    }
                    return;
                }
                this.submitting = true;
                window.pageFeedback.start();
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
            if (!navigator.onLine && (form.method || '').toLowerCase() === 'post' && !form.matches('[data-logout]')) {
                event.preventDefault();
                toast('Keine Verbindung. Bitte versuche es erneut, sobald du online bist.', { level: 'warning' });
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
                    toast(e.message, { level: 'error' });
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

    // ── Push ─────────────────────────────────────────────────────────────────
    function pushSupported() {
        return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    }

    // Berechtigung holen, Gerät abonnieren und beim Server anmelden. Ergebnis: 'on' | 'off' | 'denied'
    async function subscribePush(cfg) {
        if (await Notification.requestPermission() !== 'granted') {
            return Notification.permission === 'denied' ? 'denied' : 'off';
        }
        const reg = await navigator.serviceWorker.ready;
        const sub = (await reg.pushManager.getSubscription()) || await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(cfg.publicKey),
        });
        await postJSON(cfg.subscribeUrl, sub.toJSON());
        return 'on';
    }

    // Zustand des Geräts an den Server angleichen: vorhandenes Abo erneut melden (z.B. nach Konto-Wechsel
    // oder wenn der Server es gelöscht hat), Abo ohne Berechtigung entfernen.
    async function syncPushSubscription(cfg) {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (!sub) return 'off';
        if (Notification.permission !== 'granted') {
            await sub.unsubscribe().catch(() => {});
            return 'off';
        }
        await postJSON(cfg.subscribeUrl, sub.toJSON()).catch(() => {});
        return 'on';
    }

    // ── Bildschirm anlassen (Wake Lock) ──────────────────────────────────────
    function keepScreenOn() {
        if (!('wakeLock' in navigator)) return;
        const request = () => navigator.wakeLock.request('screen').catch(() => {});
        request();
        // Die Sperre endet beim Wegschalten der Seite: beim Zurückkommen neu anfordern
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') request();
        });
    }

    // ── Training ohne Netz abgeben ───────────────────────────────────────────
    const PENDING_KEY = 'pending-trainings';

    function pendingTrainings() {
        try {
            const list = JSON.parse(storageGet(PENDING_KEY) || '[]');
            return Array.isArray(list) ? list : [];
        } catch (e) {
            return [];
        }
    }

    function queueTraining(entry) {
        const list = pendingTrainings().filter((item) => item.run_id !== entry.run_id);
        storageSet(PENDING_KEY, JSON.stringify([...list, entry]));
    }

    let flushing = false;
    // Gespeicherte Abgaben senden. Auf der Trainingsseite selbst geht es danach direkt zur Auswertung.
    async function flushTrainings() {
        const token = document.querySelector('[name=csrfmiddlewaretoken]');
        if (flushing || !navigator.onLine || !token) return;
        // Nur Abgaben des angemeldeten Kontos senden (geteiltes Gerät, abgelaufene Sitzung)
        const user = document.body.dataset.user;
        const list = pendingTrainings().filter((item) => user && item.user === user);
        if (!list.length) return;
        flushing = true;
        const onRunPage = (run_id) => document.querySelector(`[data-training-run="${run_id}"]`);
        for (const entry of list) {
            const data = new FormData();
            data.append('csrfmiddlewaretoken', token.value);
            data.append('run_id', entry.run_id);
            data.append('question_ids', JSON.stringify(entry.question_ids));
            data.append('answers', JSON.stringify(entry.answers));
            try {
                const res = await fetch(entry.url, { method: 'POST', body: data, credentials: 'same-origin' });
                if (!res.ok) throw new Error(String(res.status));
                storageSet(PENDING_KEY, JSON.stringify(pendingTrainings().filter((item) => item.run_id !== entry.run_id)));
                if (onRunPage(entry.run_id)) {
                    window.location.href = res.url;
                    return;
                }
                toast('Dein Training ohne Verbindung wurde übermittelt.', {
                    level: 'success',
                    action: { label: 'Auswertung', run: () => { window.location.href = res.url; } },
                });
            } catch (e) {
                break; // später erneut versuchen
            }
        }
        flushing = false;
    }
    window.addEventListener('online', flushTrainings);
    document.addEventListener('DOMContentLoaded', flushTrainings);

    // ── Fragen offline nachschlagen: Daten regelmäßig auffrischen ────────────
    const OFFLINE_DATA_KEY = 'offline-data-refreshed';
    const OFFLINE_DATA_MAX_AGE = 12 * 60 * 60 * 1000;
    document.addEventListener('DOMContentLoaded', () => {
        const url = document.body.dataset.offlineData;
        if (!url || !navigator.onLine || !('serviceWorker' in navigator)) return;
        const last = parseInt(storageGet(OFFLINE_DATA_KEY), 10) || 0;
        if (Date.now() - last < OFFLINE_DATA_MAX_AGE) return;
        // Erst wenn der Service Worker die Seite kontrolliert, landet die Antwort in seinem Cache
        navigator.serviceWorker.ready.then(() => {
            if (!navigator.serviceWorker.controller) return;
            fetch(url, { credentials: 'same-origin' })
                .then((res) => { if (res.ok) storageSet(OFFLINE_DATA_KEY, String(Date.now())); })
                .catch(() => {});
        });
    });

    // Abmelden: gespeicherte Fragen, Zwischenstände und Zähler vom Gerät entfernen
    document.addEventListener('submit', (event) => {
        if (event.defaultPrevented || !event.target.matches('[data-logout]')) return;
        if (window.caches) caches.delete('la-tool-data').catch(() => {});
        [OFFLINE_DATA_KEY, PENDING_KEY].forEach((key) => storageSet(key, null));
        if (navigator.clearAppBadge) navigator.clearAppBadge().catch(() => {});
    });

    // ── Zahl am App-Symbol: ungelesene Benachrichtigungen ────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        const unread = document.body.dataset.unread;
        if (unread === undefined || !navigator.setAppBadge) return;
        const count = parseInt(unread, 10) || 0;
        (count ? navigator.setAppBadge(count) : navigator.clearAppBadge()).catch(() => {});
    });

    // ── Service Worker: registrieren, neue Version melden ────────────────────
    if ('serviceWorker' in navigator) {
        const hadController = !!navigator.serviceWorker.controller;
        let reloading = false;
        navigator.serviceWorker.addEventListener('controllerchange', () => {
            // Erste Installation übernimmt die Seite ebenfalls: nur echte Updates melden
            if (!hadController || reloading) return;
            toast('Eine neue Version des LA-Tools ist da.', {
                level: 'info',
                action: { label: 'Neu laden', run: () => { reloading = true; window.location.reload(); } },
            });
        });
        window.addEventListener('load', () => {
            const url = document.body.dataset.serviceWorker;
            if (url) navigator.serviceWorker.register(url).catch(() => {});
        });
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
