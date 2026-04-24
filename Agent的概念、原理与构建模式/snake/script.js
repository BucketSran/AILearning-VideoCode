// 获取页面元素
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const scoreElement = document.getElementById('score');
const highScoreElement = document.getElementById('highScore');
const startBtn = document.getElementById('startBtn');
const restartBtn = document.getElementById('restartBtn');
const gameOverElement = document.getElementById('gameOver');
const finalScoreElement = document.getElementById('finalScore');

// 游戏配置
const gridSize = 20;
const tileCount = canvas.width / gridSize;
const gameSpeed = 100;

// 游戏状态
let snake = [];
let food = {};
let direction = { x: 1, y: 0 };
let nextDirection = { x: 1, y: 0 };
let score = 0;
let highScore = localStorage.getItem('snakeHighScore') || 0;
let gameLoop = null;
let isGameRunning = false;

// 初始化最高分显示
highScoreElement.textContent = highScore;

// 初始化游戏
function initGame() {
    snake = [
        { x: 5, y: 10 },
        { x: 4, y: 10 },
        { x: 3, y: 10 }
    ];
    
    direction = { x: 1, y: 0 };
    nextDirection = { x: 1, y: 0 };
    
    score = 0;
    scoreElement.textContent = score;
    
    generateFood();
    
    gameOverElement.style.display = 'none';
}

// 生成食物
function generateFood() {
    let validPosition = false;
    
    while (!validPosition) {
        food = {
            x: Math.floor(Math.random() * tileCount),
            y: Math.floor(Math.random() * tileCount)
        };
        
        validPosition = !snake.some(segment => segment.x === food.x && segment.y === food.y);
    }
}

// 绘制游戏画面
function draw() {
    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    ctx.strokeStyle = '#1a1a3e';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= tileCount; i++) {
        ctx.beginPath();
        ctx.moveTo(i * gridSize, 0);
        ctx.lineTo(i * gridSize, canvas.height);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(0, i * gridSize);
        ctx.lineTo(canvas.width, i * gridSize);
        ctx.stroke();
    }
    
    ctx.fillStyle = '#ef4444';
    ctx.shadowColor = '#ef4444';
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.arc(food.x * gridSize + gridSize / 2, food.y * gridSize + gridSize / 2, gridSize / 2 - 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    
    snake.forEach((segment, index) => {
        if (index === 0) {
            ctx.fillStyle = '#4ade80';
            ctx.shadowColor = '#4ade80';
            ctx.shadowBlur = 10;
        } else {
            const greenValue = Math.max(100, 180 - index * 10);
            ctx.fillStyle = 'rgb(34, ' + greenValue + ', 80)';
            ctx.shadowBlur = 0;
        }
        
        const padding = 2;
        ctx.beginPath();
        ctx.roundRect(
            segment.x * gridSize + padding,
            segment.y * gridSize + padding,
            gridSize - padding * 2,
            gridSize - padding * 2,
            5
        );
        ctx.fill();
    });
    
    if (snake.length > 0) {
        const head = snake[0];
        ctx.fillStyle = '#fff';
        
        let eye1X = head.x * gridSize + gridSize / 4;
        let eye2X = head.x * gridSize + gridSize * 3 / 4;
        let eye1Y = head.y * gridSize + gridSize / 3;
        let eye2Y = head.y * gridSize + gridSize * 2 / 3;
        
        if (direction.x === 1) {
            eye1X = head.x * gridSize + gridSize * 2 / 3;
            eye2X = head.x * gridSize + gridSize * 2 / 3;
        } else if (direction.x === -1) {
            eye1X = head.x * gridSize + gridSize / 3;
            eye2X = head.x * gridSize + gridSize / 3;
        }
        
        if (direction.y === -1) {
            eye1Y = head.y * gridSize + gridSize / 3;
            eye2Y = head.y * gridSize + gridSize / 3;
        } else if (direction.y === 1) {
            eye1Y = head.y * gridSize + gridSize * 2 / 3;
            eye2Y = head.y * gridSize + gridSize * 2 / 3;
        }
        
        ctx.beginPath();
        ctx.arc(eye1X, eye1Y, 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(eye2X, eye2Y, 2, 0, Math.PI * 2);
        ctx.fill();
    }
}

// 更新游戏状态
function update() {
    direction = { x: nextDirection.x, y: nextDirection.y };
    
    const head = {
        x: snake[0].x + direction.x,
        y: snake[0].y + direction.y
    };
    
    if (head.x < 0 || head.x >= tileCount || head.y < 0 || head.y >= tileCount) {
        gameOver();
        return;
    }
    
    if (snake.some(segment => segment.x === head.x && segment.y === head.y)) {
        gameOver();
        return;
    }
    
    snake.unshift(head);
    
    if (head.x === food.x && head.y === food.y) {
        score += 10;
        scoreElement.textContent = score;
        generateFood();
    } else {
        snake.pop();
    }
}

// 游戏结束
function gameOver() {
    clearInterval(gameLoop);
    isGameRunning = false;
    
    if (score > highScore) {
        highScore = score;
        localStorage.setItem('snakeHighScore', highScore);
        highScoreElement.textContent = highScore;
    }
    
    finalScoreElement.textContent = score;
    gameOverElement.style.display = 'block';
    
    startBtn.style.display = 'none';
    restartBtn.style.display = 'inline-block';
}

// 开始游戏
function startGame() {
    if (isGameRunning) return;
    
    initGame();
    isGameRunning = true;
    
    gameOverElement.style.display = 'none';
    
    startBtn.style.display = 'none';
    restartBtn.style.display = 'inline-block';
    
    gameLoop = setInterval(function() {
        update();
        draw();
    }, gameSpeed);
}

// 键盘控制
document.addEventListener('keydown', function(e) {
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' '].indexOf(e.key) !== -1) {
        e.preventDefault();
    }
    
    if (!isGameRunning) return;
    
    switch (e.key) {
        case 'ArrowUp':
        case 'w':
        case 'W':
            if (direction.y !== 1) {
                nextDirection = { x: 0, y: -1 };
            }
            break;
        case 'ArrowDown':
        case 's':
        case 'S':
            if (direction.y !== -1) {
                nextDirection = { x: 0, y: 1 };
            }
            break;
        case 'ArrowLeft':
        case 'a':
        case 'A':
            if (direction.x !== 1) {
                nextDirection = { x: -1, y: 0 };
            }
            break;
        case 'ArrowRight':
        case 'd':
        case 'D':
            if (direction.x !== -1) {
                nextDirection = { x: 1, y: 0 };
            }
            break;
    }
});

// 按钮事件
startBtn.addEventListener('click', startGame);
restartBtn.addEventListener('click', startGame);

// 初始绘制
initGame();
draw();