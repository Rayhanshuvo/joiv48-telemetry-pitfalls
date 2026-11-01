package com.example.autoscaledemo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.Random;

@RestController
public class DemoController {

    private final Random random = new Random();

    @GetMapping("/work")
    public String doWork(@RequestParam(defaultValue = "5") int ms) throws InterruptedException {
        // Simulate a small amount of processing time per request.
        // Adjust "ms" via query param to tune how CPU-bound this endpoint is.
        long start = System.nanoTime();
        double x = 0;
        while ((System.nanoTime() - start) / 1_000_000 < ms) {
            x += Math.sqrt(random.nextDouble());
        }
        return "ok:" + x;
    }

    @GetMapping("/health")
    public String health() {
        return "ok";
    }
}
