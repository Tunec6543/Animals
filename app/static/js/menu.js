(function () {
    var button = document.querySelector('.burger');
    var menu = document.getElementById('main-menu');
    if (!button || !menu) {
        return;
    }
    button.addEventListener('click', function () {
        var isOpen = menu.classList.toggle('is-open');
        button.setAttribute('aria-expanded', String(isOpen));
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && menu.classList.contains('is-open')) {
            menu.classList.remove('is-open');
            button.setAttribute('aria-expanded', 'false');
            button.focus();
        }
    });
})();
