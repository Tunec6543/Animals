(function () {
    var STORAGE_KEY = 'favoritePets';
    var form = document.querySelector('form[data-live-url]');
    var results = document.getElementById('catalog-results');
    var status = document.getElementById('catalog-status');
    var favToggle = document.getElementById('fav-toggle');
    var favCount = document.getElementById('fav-count');
    var favOnly = false;
    var timer = null;
    var controller = null;

    function readFavorites() {
        try {
            var list = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
            return Array.isArray(list) ? list : [];
        } catch (error) {
            return [];
        }
    }

    function writeFavorites(list) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
        } catch (error) {
            return;
        }
    }

    function syncFavorites() {
        var list = readFavorites();
        document.querySelectorAll('[data-fav]').forEach(function (button) {
            var active = list.indexOf(button.dataset.fav) !== -1;
            button.setAttribute('aria-pressed', String(active));
            button.classList.toggle('is-active', active);
        });
        if (favCount) {
            favCount.textContent = list.length;
        }
    }

    function buildQuery() {
        var params = new URLSearchParams();
        var q = form.elements.q.value.trim();
        if (q) {
            params.set('q', q);
        }
        if (form.elements.species.value) {
            params.set('species', form.elements.species.value);
        }
        if (favOnly) {
            params.set('ids', readFavorites().join(','));
        }
        return params.toString();
    }

    function setLoading(isLoading) {
        results.classList.toggle('is-loading', isLoading);
        results.setAttribute('aria-busy', String(isLoading));
        status.classList.toggle('is-loading', isLoading);
    }

    function load(query) {
        var current = new AbortController();
        clearTimeout(timer);
        if (controller) {
            controller.abort();
        }
        controller = current;
        setLoading(true);
        status.textContent = 'Загрузка…';
        fetch(form.dataset.liveUrl + '?' + query, {
            signal: current.signal,
            headers: { 'Accept': 'application/json' }
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.json();
            })
            .then(function (data) {
                results.innerHTML = data.html;
                status.textContent = 'Найдено питомцев: ' + data.count;
                syncFavorites();
            })
            .catch(function (error) {
                if (error.name !== 'AbortError') {
                    status.textContent = 'Не удалось загрузить каталог. Попробуйте ещё раз.';
                }
            })
            .finally(function () {
                if (controller === current) {
                    setLoading(false);
                }
            });
    }

    document.addEventListener('click', function (event) {
        var button = event.target.closest('[data-fav]');
        if (button) {
            var list = readFavorites();
            var index = list.indexOf(button.dataset.fav);
            if (index === -1) {
                list.push(button.dataset.fav);
            } else {
                list.splice(index, 1);
            }
            writeFavorites(list);
            syncFavorites();
            if (favOnly && form && results) {
                load(buildQuery());
            }
            return;
        }
        var link = event.target.closest('.pagination__link[href]');
        if (link && form && results && results.contains(link)) {
            event.preventDefault();
            load(link.search.slice(1));
            results.scrollIntoView({ block: 'start' });
        }
    });

    if (form && results && status) {
        form.addEventListener('submit', function (event) {
            event.preventDefault();
            clearTimeout(timer);
            load(buildQuery());
        });
        form.elements.q.addEventListener('input', function () {
            clearTimeout(timer);
            timer = setTimeout(function () {
                load(buildQuery());
            }, 300);
        });
        form.elements.species.addEventListener('change', function () {
            load(buildQuery());
        });
        if (favToggle) {
            favToggle.addEventListener('click', function () {
                favOnly = !favOnly;
                favToggle.setAttribute('aria-pressed', String(favOnly));
                load(buildQuery());
            });
        }
    }

    syncFavorites();
})();
