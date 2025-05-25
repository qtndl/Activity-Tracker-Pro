// Функция для создания круговой диаграммы
function createResponsePieChart() {
    const ctx = document.getElementById('responsePieChart');
    if (!ctx) return;

    // Получаем данные из summary
    const totalMessages = parseInt(document.getElementById('totalMessages').textContent) || 0;
    const respondedMessages = parseInt(document.getElementById('respondedMessages').textContent) || 0;
    const missedMessages = parseInt(document.getElementById('missedMessages').textContent) || 0;
    const inProgress = Math.max(0, totalMessages - respondedMessages - missedMessages);

    // Создаем диаграмму
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Отвечено', 'Пропущено', 'В обработке'],
            datasets: [{
                data: [respondedMessages, missedMessages, inProgress],
                backgroundColor: ['#4facfe', '#ff6b9d', '#feca57'],
                borderWidth: 0,
                hoverBorderWidth: 4,
                hoverBorderColor: '#fff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '70%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: 'rgba(255, 255, 255, 0.8)',
                        padding: 25,
                        usePointStyle: true,
                        font: { size: 14, weight: 600 }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const value = context.raw;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = Math.round((value / total) * 100);
                            return `${context.label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            },
            animation: {
                duration: 2000,
                easing: 'easeOutBounce'
            }
        }
    });
}

// Вызываем функцию при загрузке страницы
document.addEventListener('DOMContentLoaded', createResponsePieChart); 