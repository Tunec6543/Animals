(function () {
    var emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    var phonePattern = /^\+?[\d\s()-]+$/;

    function getMessage(field) {
        var value = field.value.trim();
        if (!value) {
            return field.required ? 'Заполните это поле.' : '';
        }
        if (field.type === 'email' && !emailPattern.test(value)) {
            return 'Введите корректный email, например name@example.com.';
        }
        if (field.type === 'tel') {
            var digits = value.replace(/\D/g, '');
            if (!phonePattern.test(value) || digits.length < 10 || digits.length > 15) {
                return 'Введите телефон в формате +7 900 000-00-00.';
            }
        }
        if (field.type === 'number') {
            var number = Number(value);
            if (isNaN(number)) {
                return 'Введите число.';
            }
            if (field.min !== '' && number < Number(field.min)) {
                return 'Минимальное значение: ' + field.min + '.';
            }
            if (field.max !== '' && number > Number(field.max)) {
                return 'Максимальное значение: ' + field.max + '.';
            }
        }
        if (field.minLength > 0 && value.length < field.minLength) {
            return 'Минимум символов: ' + field.minLength + '. Сейчас: ' + value.length + '.';
        }
        if (field.maxLength > 0 && value.length > field.maxLength) {
            return 'Максимум символов: ' + field.maxLength + '.';
        }
        return '';
    }

    function getErrorBox(field) {
        var id = field.id + '_error';
        var box = document.getElementById(id);
        if (!box) {
            box = document.createElement('p');
            box.className = 'field__error';
            box.id = id;
            field.insertAdjacentElement('afterend', box);
        }
        return box;
    }

    function showError(field, message) {
        var box = getErrorBox(field);
        box.textContent = message;
        if (message) {
            field.setAttribute('aria-invalid', 'true');
            field.setAttribute('aria-describedby', box.id);
        } else {
            field.removeAttribute('aria-invalid');
            field.removeAttribute('aria-describedby');
        }
    }

    function getFields(form) {
        return Array.prototype.filter.call(form.elements, function (el) {
            return el.id && el.type !== 'hidden' && el.type !== 'submit' && el.type !== 'button';
        });
    }

    function init(form) {
        getFields(form).forEach(function (field) {
            var box = document.getElementById(field.id + '_error');
            if (box && box.textContent.trim()) {
                field.setAttribute('aria-invalid', 'true');
                field.setAttribute('aria-describedby', box.id);
            }
            field.addEventListener('input', function () {
                showError(field, '');
            });
            field.addEventListener('blur', function () {
                if (field.value.trim()) {
                    showError(field, getMessage(field));
                }
            });
        });

        form.addEventListener('submit', function (event) {
            var firstInvalid = null;
            getFields(form).forEach(function (field) {
                var message = getMessage(field);
                showError(field, message);
                if (message && !firstInvalid) {
                    firstInvalid = field;
                }
            });
            if (firstInvalid) {
                event.preventDefault();
                firstInvalid.focus();
            }
        });
    }

    document.querySelectorAll('form[data-validate]').forEach(init);
})();
