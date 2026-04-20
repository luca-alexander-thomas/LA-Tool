class Calendar {
    constructor(eventData = {}) {
        this.currentDate = new Date();
        this.eventData = eventData;
        this.selectedDate = null;
        this.init();
    }

    init() {
        document.getElementById('prevMonth').addEventListener('click', () => this.prevMonth());
        document.getElementById('nextMonth').addEventListener('click', () => this.nextMonth());
        this.render();
    }

    prevMonth() {
        this.currentDate.setMonth(this.currentDate.getMonth() - 1);
        this.render();
    }

    nextMonth() {
        this.currentDate.setMonth(this.currentDate.getMonth() + 1);
        this.render();
    }

    render() {
        this.updateHeader();
        this.generateCalendarDays();
    }

    updateHeader() {
        const options = { year: 'numeric', month: 'long' };
        const monthYear = this.currentDate.toLocaleDateString('de-DE', options);
        document.getElementById('monthYear').textContent = monthYear.charAt(0).toUpperCase() + monthYear.slice(1);
    }

    generateCalendarDays() {
        const year = this.currentDate.getFullYear();
        const month = this.currentDate.getMonth();

        const firstDay = new Date(year, month, 1);
        
        // Berechne den Startpunkt (Montag der Woche, in der der 1. Tag liegt)
        // getDay() gibt 0 = Sonntag, 1 = Montag, etc.
        const dayOfWeek = firstDay.getDay();
        const startDate = new Date(firstDay);
        // Wenn Sonntag (0), gehe 6 Tage zurück; sonst gehe (dayOfWeek - 1) Tage zurück
        const offset = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
        startDate.setDate(startDate.getDate() - offset);

        const calendarDaysContainer = document.getElementById('calendarDays');
        calendarDaysContainer.innerHTML = '';

        // 42 Felder = 6 Wochen
        for (let i = 0; i < 42; i++) {
            const date = new Date(startDate);
            date.setDate(date.getDate() + i);

            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day';
            dayElement.innerHTML = `<span class="calendar-day-number">${date.getDate()}</span>`;

            // Andere Monate grau färben
            if (date.getMonth() !== month) {
                dayElement.classList.add('other-month');
            }

            // Heute markieren
            const today = new Date();
            if (date.toDateString() === today.toDateString()) {
                dayElement.classList.add('today');
            }

            const dateString = this.formatDate(date);
            
            // Event-Punkt hinzufügen
            if (this.eventData[dateString] && this.eventData[dateString].length > 0) {
                dayElement.classList.add('has-event');
            }

            // Selected Datum hervorheben
            if (this.selectedDate === dateString) {
                dayElement.classList.add('selected');
            }

            // Click-Handler
            dayElement.addEventListener('click', () => {
                this.selectDate(dateString, dayElement);
            });

            calendarDaysContainer.appendChild(dayElement);
        }
    }

    selectDate(dateString, dayElement) {
        // Nur Daten mit Events sind klickbar
        if (!this.eventData[dateString]) {
            return;
        }

        // Vorherige Auswahl entfernen
        document.querySelectorAll('.calendar-day.selected').forEach(el => {
            el.classList.remove('selected');
        });

        // Neue Auswahl hinzufügen
        this.selectedDate = dateString;
        dayElement.classList.add('selected');

        // Event-Liste aktualisieren
        this.updateEventList(dateString);
    }

    updateEventList(dateString) {
        const events = this.eventData[dateString] || [];
        const eventListContainer = document.getElementById('eventList');
        const selectedDateTitle = document.getElementById('selectedDateTitle');

        // Datum formatieren
        const date = new Date(dateString + 'T00:00:00');
        const formattedDate = date.toLocaleDateString('de-DE', { 
            weekday: 'long', 
            year: 'numeric', 
            month: 'long', 
            day: 'numeric' 
        });

        selectedDateTitle.textContent = `Events am ${formattedDate}`;

        if (events.length === 0) {
            eventListContainer.innerHTML = '<p class="no-events-message">Keine Events an diesem Datum</p>';
            return;
        }

        eventListContainer.innerHTML = '';
        events.forEach(event => {
            const eventElement = document.createElement('div');
            eventElement.className = 'event-item';
            eventElement.innerHTML = `
                <div>
                    <p class="event-item-title">${event.title}</p>
                </div>
                <div class="event-item-link">
                    <a href="${event.link || '#'}">
                        <svg class="bi bi-chevron-right" xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" fill="currentColor" viewBox="0 0 16 16">
                            <path fill-rule="evenodd" d="M4.646 1.646a.5.5 0 0 1 .708 0l6 6a.5.5 0 0 1 0 .708l-6 6a.5.5 0 0 1-.708-.708L10.293 8 4.646 2.354a.5.5 0 0 1 0-.708z"></path>
                        </svg>
                    </a>
                </div>
            `;
            eventListContainer.appendChild(eventElement);
        });
    }

    formatDate(date) {
        const d = String(date.getDate()).padStart(2, '0');
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const y = date.getFullYear();
        return `${y}-${m}-${d}`;
    }
}

// Initialisierung mit Beispiel-Events
const eventData = {
    '2026-01-06': [
        { title: 'Thema 1', link: 'work-detail.html?id=1' },
        { title: 'Workshop Grundlagen', link: 'work-detail.html?id=2' }
    ],
    '2026-01-15': [
        { title: 'Thema 2', link: 'work-detail.html?id=3' }
    ],
    '2026-01-22': [
        { title: 'Fortgeschrittenes Thema', link: 'work-detail.html?id=4' }
    ],
    '2026-02-02': [
        { title: 'Thema 3', link: 'work-detail.html?id=5' },
        { title: 'Praxis-Übung', link: 'work-detail.html?id=6' }
    ],
    '2026-02-14': [
        { title: 'Special Event', link: 'work-detail.html?id=7' }
    ],
    '2026-03-29': [
        { title: 'Heute Dienst', link: 'work-detail.html?id=8' }
    ]
};

// Kalender starten, sobald DOM geladen ist
document.addEventListener('DOMContentLoaded', function() {
    const calendar = new Calendar(eventData);
});