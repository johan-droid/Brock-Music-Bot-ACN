class CircuitBreaker {
    constructor({ failureThreshold = 5, resetTimeout = 30000 }) {
        this.failureThreshold = failureThreshold;
        this.resetTimeout = resetTimeout;
        this.state = 'CLOSED';
        this.failureCount = 0;
        this.nextAttempt = Date.now();
    }

    async execute(action, args = [], options = {}) {
        if (this.state === 'OPEN') {
            if (this.nextAttempt <= Date.now()) {
                this.state = 'HALF_OPEN';
            } else {
                const err = new Error('Circuit breaker is open');
                err.status = 503;
                throw err;
            }
        }

        let retries = options.maxRetries || 0;

        while (true) {
            try {
                const result = await action(...args);
                this.onSuccess();
                return result;
            } catch (error) {
                 if (retries > 0) {
                     retries--;
                     continue;
                 }
                this.onFailure();
                throw error;
            }
        }
    }

    onSuccess() {
        this.failureCount = 0;
        this.state = 'CLOSED';
    }

    onFailure() {
        this.failureCount++;
        if (this.failureCount >= this.failureThreshold) {
            this.state = 'OPEN';
            this.nextAttempt = Date.now() + this.resetTimeout;
        }
    }
}

module.exports = CircuitBreaker;
