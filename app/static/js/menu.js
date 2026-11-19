(function () {
    var button = document.querySelector('.burger');
    var menu = document.getElementById('main-menu');
    if (!button || !menu) {
        return;
    }

    function setOpen(isOpen) {
        menu.classList.toggle('is-open', isOpen);
        button.setAttribute('aria-expanded', String(isOpen));
    }

    button.addEventListener('click', function () {
        setOpen(!menu.classList.contains('is-open'));
    });

    document.addEventListener('click', function (event) {
        if (!event.target.closest('.site-header')) {
            setOpen(false);
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && menu.classList.contains('is-open')) {
            setOpen(false);
            button.focus();
        }
    });

    var desktop = window.matchMedia('(min-width: 1101px)');

    function onResize(event) {
        if (event.matches) {
            setOpen(false);
        }
    }

    if (desktop.addEventListener) {
        desktop.addEventListener('change', onResize);
    } else if (desktop.addListener) {
        desktop.addListener(onResize);
    }
})();
