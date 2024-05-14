import cv2
import numpy as np
from collections import deque
import random
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.optim.lr_scheduler import StepLR
from gameTRY import Breakout
import time
import matplotlib.pyplot as plt
from preprocessing import *

def avg(r):
    return [np.mean(r[i - 100:i]) for i in range(100, len(r))]

def plot_metrics(losses, rewards, epsilons):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 12))
    
    # # Plot loss
    # ax1.plot(losses)
    # ax1.set_xlabel('Iteration')
    # ax1.set_ylabel('Loss')
    # ax1.set_title('Training Loss')
    avg_losses = avg(losses)  # Calculate average losses
    ax1.plot(range(100, len(losses)), avg_losses)  # Start plotting from 100th iteration
    ax1.set_xlabel('Iteration')
    ax1.set_ylabel('Average Loss')
    ax1.set_title('Average Training Loss over the last 100 iterations')
    
    # Plot rewards
    ax2.plot(rewards)
    ax2.set_xlabel('Iteration')
    ax2.set_ylabel('Reward')
    ax2.set_title('Training Rewards')
    
    # Plot epsilon
    ax3.plot(epsilons)
    ax3.set_xlabel('Iteration')
    ax3.set_ylabel('Epsilon')
    ax3.set_title('Exploration Rate (Epsilon)')
    
    plt.tight_layout()
    plt.show()
    
def train(model, start):
    optimizer = optim.Adam(model.parameters(), lr=0.0002)
    scheduler = StepLR(optimizer, step_size=10000, gamma=0.9)

    criterion = nn.MSELoss() # crossentropy
    game_state = Breakout()

    D = deque()
    losses = []
    rewards = []
    epsilons = []

    # initial action is do nothing
    action = torch.zeros([model.number_of_actions], dtype=torch.float32)
    action[0] = 0
    
    image_data, reward, terminal = game_state.take_action(action)
    image_data = preprocessing(image_data)
    state = torch.cat((image_data, image_data, image_data, image_data)).unsqueeze(0) # 1-4-84-84

    # initialize epsilon value
    epsilon = model.initial_epsilon
    iteration = 0

    #epsilon = 0.0927
    #iteration = 420000
    # main infinite loop
    while iteration < model.number_of_iterations:
        # get output from the neural network
        output = model(state)[0] # Output size = torch.Size([2]) tensor([-0.0278,  1.7244]
        #output = model(state)

        # initialize action
        action = torch.zeros([model.number_of_actions], dtype=torch.float32)

        # epsilon greedy exploration
        random_action = random.random() <= epsilon
        if random_action:
            print("Random action!")

        # Pick action --> random or index of maximum q value
        action_index = [torch.randint(model.number_of_actions, torch.Size([]), dtype=torch.int)
                        if random_action
                        else torch.argmax(output)][0]

        #print("Action index shape: ", action_index.shape) # torch.Size([])
       
        action[action_index] = 1

        if epsilon > model.final_epsilon:
            epsilon -= (model.initial_epsilon - model.final_epsilon) / model.explore
        
        epsilons.append(epsilon)
        # get next state and reward
        image_data_1, reward, terminal = game_state.take_action(action)
        image_data_1 = preprocessing(image_data_1)
        
        #print("İmage data_1 shape: ", image_data_1.shape)  # 1-84-84

        state_1 = torch.cat((state.squeeze(0)[1:, :, :], image_data_1)).unsqueeze(0)   # squeeze(0).shape = 4-84-84
        #print("State_1 Shape: ", state_1.shape) # State_1 Shape = ([1, 4, 84, 84])     # squeeze(0)[1:,:,:].shape = 3-84-84
        action = action.unsqueeze(0)
        #print("Action size: ", action.shape) # 1-2
        reward = torch.from_numpy(np.array([reward], dtype=np.float32)).unsqueeze(0)   
        #print("Reward size: ", reward.shape)
        # save transition to replay memory
        D.append((state, action, reward, state_1, terminal))

        # if replay memory is full, remove the oldest transition
        if len(D) > model.replay_memory_size:
            D.popleft()

        # sample random minibatch
        # it picks k unique random elements, a sample, from a sequence: random.sample(population, k)
        minibatch = random.sample(D, min(len(D), model.minibatch_size))
        # unpack minibatch

        state_batch   = torch.cat(tuple(d[0] for d in minibatch))
        # print("state_batch size: ", state_batch.shape)
        action_batch  = torch.cat(tuple(d[1] for d in minibatch))
        # print("action_batch size: ", action_batch.shape)
        reward_batch  = torch.cat(tuple(d[2] for d in minibatch))
        # print("reward_batch size: ", reward_batch.shape)
        state_1_batch = torch.cat(tuple(d[3] for d in minibatch))
        # print("state_1_batch size: ", state_1_batch.shape)
        
        # get output for the next state
        output_1_batch = model(state_1_batch)
        #print("output_1_batch: " , output_1_batch.shape)

        # set y_j to r_j for terminal state, otherwise to r_j + gamma*max(Q) Target Q value Bellman equation.
        y_batch = torch.cat(tuple(reward_batch[i] if minibatch[i][4]
                                  else reward_batch[i] + model.gamma * torch.max(output_1_batch[i])
                                  for i in range(len(minibatch))))

        
        # extract Q-value -----> column1 * column1 + column2 * column2
        # The main idea behind Q-learning is that if we had a function Q∗ :State × Action → ℝ
        #that could tell us what our return would be, if we were to take an action in a given state,
        #then we could easily construct a policy that maximizes our rewards
        q_value = torch.sum(model(state_batch) * action_batch, dim=1)
        #print("q_value: ", q_value.shape)

        # PyTorch accumulates gradients by default, so they need to be reset in each pass
        optimizer.zero_grad()

        # returns a new Tensor, detached from the current graph, the result will never require gradient
        y_batch = y_batch.detach()

        # calculate loss
        loss = criterion(q_value, y_batch)
        losses.append(loss.item())

        # do backward pass
        loss.backward()
        optimizer.step()
        
        # update learning rate
        scheduler.step()

        # set state to be state_1
        state = state_1
        iteration += 1
        
        rewards.append(reward.numpy()[0][0])

        if iteration % 10000 == 0:
            torch.save(model, "trained_model/current_model_" + str(iteration) + ".pth")
              
        print("total iteration: {} Elapsed time: {:.2f} epsilon: {:.5f}"
               " action: {} Reward: {:.1f}".format(iteration,((time.time() - start)/60),epsilon,action_index.cpu().detach().numpy(),reward.numpy()[0][0]))

    plot_metrics(losses, rewards, epsilons)
